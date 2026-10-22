# SPDX-License-Identifier: GPL-2.0-or-later
"""Explicit read-only tracing selection shared by CLI and desktop launchers."""
import hashlib
from pathlib import Path

KEYS={'trace_plugin','trace_calls','trace_watch','trace_cpu','trace_limit','trace_per_site'}
WATCH_KEYS=('lo','hi','pclo','pchi')


def integer(value, name, low=0, high=(1<<64)-1):
    if type(value) is not int or not low<=value<=high:
        raise ValueError(f'{name} must be an integer in {low}..{high}')
    return value


def configuration(config):
    selected={key:config[key] for key in KEYS if key in config}
    if not selected:return None
    path=selected.get('trace_plugin')
    if not isinstance(path,str) or not Path(path).is_absolute() or not Path(path).is_file() or ',' in path:
        raise ValueError('trace_plugin must name an existing absolute plugin file without commas')
    calls=selected.get('trace_calls',[])
    if not isinstance(calls,list) or len(calls)>32:
        raise ValueError('trace_calls must contain at most 32 instruction addresses')
    for value in calls:
        integer(value,'trace call',1)
        if value&1:raise ValueError('Trace addresses must be even; remove a Thumb pointer tag explicitly')
    if len(set(calls))!=len(calls):raise ValueError('Trace addresses must be unique')
    watch=selected.get('trace_watch')
    if watch is not None:
        if not isinstance(watch,dict) or set(watch)!=set(WATCH_KEYS):
            raise ValueError('trace_watch requires exactly lo, hi, pclo and pchi')
        for key in WATCH_KEYS:integer(watch[key],'trace_watch '+key)
        if watch['lo']>=watch['hi'] or watch['pclo']>=watch['pchi']:
            raise ValueError('Trace watch address/code ranges must be increasing and end-exclusive')
    if not calls and watch is None:raise ValueError('Trace requires explicit call addresses or a memory/code watch range')
    result=dict(plugin=str(Path(path).resolve()),calls=list(calls),watch=dict(watch) if watch else None,
                limit=integer(selected.get('trace_limit',10000),'trace_limit',1,1000000),
                per_site=integer(selected.get('trace_per_site',4),'trace_per_site',1,1000000))
    result['cpu']=integer(selected['trace_cpu'],'trace_cpu',0,15) if 'trace_cpu' in selected else None
    return result


def cli_args(profile):
    if profile is None:return []
    args=['--trace-plugin',profile['plugin'],'--trace-limit',str(profile['limit']),
          '--trace-per-site',str(profile['per_site'])]
    for pc in profile['calls']:args+=['--trace-call',hex(pc)]
    if profile['watch']:
        args+=['--trace-watch',':'.join(hex(profile['watch'][key]) for key in WATCH_KEYS)]
    if profile['cpu'] is not None:args+=['--trace-cpu',str(profile['cpu'])]
    return args


def arguments(parser):
    parser.add_argument('--trace-plugin',help='Optional locally built read-only QEMU trace plugin')
    parser.add_argument('--trace-call',type=lambda x:int(x,0),action='append',dest='trace_calls',help='Explicit instruction address; repeat at most 32 times')
    parser.add_argument('--trace-watch',help='Explicit LO:HI:PCLO:PCHI end-exclusive store-watch ranges')
    parser.add_argument('--trace-cpu',type=int,help='Optional vCPU index 0..15')
    parser.add_argument('--trace-limit',type=int,help='Maximum output records, default 10000')
    parser.add_argument('--trace-per-site',type=int,help='Maximum records per CPU/PC/address, default 4')


def validate(args):
    config={key:getattr(args,key) for key in KEYS if getattr(args,key,None) is not None}
    if 'trace_watch' in config:
        parts=config['trace_watch'].split(':')
        if len(parts)!=4:raise ValueError('Trace watch requires LO:HI:PCLO:PCHI')
        try:config['trace_watch']={key:int(value,0) for key,value in zip(WATCH_KEYS,parts)}
        except ValueError:raise ValueError('Trace ranges must be integers') from None
    return configuration(config)


def attach(guest, profile):
    if profile is None:return
    output=guest.out/'plugin-trace.log'
    if ',' in str(output):raise ValueError('Trace output path cannot contain a comma')
    options=[profile['plugin'],'out='+str(output),'limit='+str(profile['limit']),
             'per_site='+str(profile['per_site'])]
    if profile['calls']:options+=['calls='+':'.join(hex(x) for x in profile['calls'])]
    if profile['watch']:options += [key+'='+hex(profile['watch'][key]) for key in WATCH_KEYS]
    if profile['cpu'] is not None:options+=['cpu='+str(profile['cpu'])]
    guest.command+=['-plugin',','.join(options)]
    with Path(profile['plugin']).open('rb') as source:digest=hashlib.file_digest(source,'sha256').hexdigest()
    guest.data['trace_plugin']=dict(profile,plugin_sha256=digest,output=str(output),
        observation_only_requested=True,firmware_addresses_inferred=False,clock='host_monotonic_us')
