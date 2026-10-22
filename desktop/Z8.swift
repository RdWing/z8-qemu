// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 RdWing
import AppKit
import WebKit
import Darwin

// Bounded plain-text snapshots; never follow a replaced log into another file
// type or block the UI on a FIFO. The full private disk log remains untouched.
func readDiagnosticLog(_ url: URL, limit: Int = 131072) -> String {
    let fd = Darwin.open(url.path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK)
    guard fd >= 0 else { return "Log unavailable: " + String(cString: strerror(errno)) }
    defer { Darwin.close(fd) }
    var info = stat()
    guard fstat(fd, &info) == 0, info.st_mode & S_IFMT == S_IFREG else { return "Log unavailable: expected a regular file." }
    let count = Int(min(Int64(max(0, limit)), max(0, info.st_size)))
    guard count > 0 else { return "No output yet." }
    var bytes = [UInt8](repeating: 0, count: count)
    let read = bytes.withUnsafeMutableBytes { buffer in
        pread(fd, buffer.baseAddress, count, max(0, info.st_size - Int64(count)))
    }
    guard read >= 0 else { return "Log unavailable: " + String(cString: strerror(errno)) }
    let text = String(decoding: bytes.prefix(read), as: UTF8.self)
    return text.unicodeScalars.map { scalar in
        (scalar.value < 32 && ![9, 10, 13].contains(scalar.value)) || scalar.value == 127
            ? String(format: "\\x%02X", scalar.value) : String(scalar)
    }.joined()
}

final class Diagnostics: NSObject {
    let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 840, height: 520),
        styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
    let source = NSPopUpButton(frame: .zero, pullsDown: false)
    let pause = NSButton(title: "Pause", target: nil, action: nil)
    let text = NSTextView()
    var timer: Timer?
    var output: URL?
    var revision = UUID()
    var paused = false
    var reading = false

    override init() {
        super.init()
        window.title = "Z8 diagnostics"; window.isReleasedWhenClosed = false
        window.minSize = NSSize(width: 640, height: 320); window.center()
        source.addItems(withTitles: ["MAIN UART TX", "QEMU diagnostics", "Launcher",
            "EX USART1 TX", "EX USART2 TX", "EX USART3 TX", "EX UART4 TX", "EX UART5 TX", "EX USART6 TX", "Plugin trace"])
        source.menu?.autoenablesItems = false
        source.selectItem(at: 0); source.target = self; source.action = #selector(changeSource)
        source.setAccessibilityLabel("Diagnostic source")
        pause.target = self; pause.action = #selector(togglePause)
        let label = NSTextField(wrappingLabelWithString: "Read only · latest 128 KiB · full logs stay in the session folder. MAIN channels are combined; EX streams are separate. Command input is unavailable.")
        label.textColor = .secondaryLabelColor
        let controls = NSStackView(views: [source, pause]); controls.spacing = 12
        let scroll = NSScrollView(); scroll.hasVerticalScroller = true; scroll.hasHorizontalScroller = true
        text.isEditable = false; text.isSelectable = true; text.isRichText = false
        text.font = .monospacedSystemFont(ofSize: 12, weight: .regular)
        text.autoresizingMask = [.width]; text.isVerticallyResizable = true
        text.textContainer?.widthTracksTextView = true
        text.setAccessibilityLabel("Diagnostic output"); scroll.documentView = text
        let stack = NSStackView(views: [controls, label, scroll]); stack.orientation = .vertical
        stack.alignment = .leading; stack.spacing = 12; stack.translatesAutoresizingMaskIntoConstraints = false
        window.contentView!.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: window.contentView!.leadingAnchor, constant: 16),
            stack.trailingAnchor.constraint(equalTo: window.contentView!.trailingAnchor, constant: -16),
            stack.topAnchor.constraint(equalTo: window.contentView!.topAnchor, constant: 16),
            stack.bottomAnchor.constraint(equalTo: window.contentView!.bottomAnchor, constant: -16),
            scroll.widthAnchor.constraint(equalTo: stack.widthAnchor),
            label.widthAnchor.constraint(equalTo: stack.widthAnchor)
        ])
        timer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] _ in self?.refresh() }
    }
    deinit { timer?.invalidate() }
    func setOutput(_ output: URL?, nativeEX: Bool, trace: Bool) {
        self.output = output; revision = UUID(); paused = false; pause.title = "Pause"
        for index in 3...8 { source.item(at: index)?.isEnabled = nativeEX }
        source.item(at: 9)?.isEnabled = trace
        if (!nativeEX && (3...8).contains(source.indexOfSelectedItem)) || (!trace && source.indexOfSelectedItem == 9) { source.selectItem(at: 0) }
        text.string = "Waiting for session logs…"
        refresh(force: true)
    }
    func show() { window.makeKeyAndOrderFront(nil); refresh(force: true) }
    @objc func changeSource() {
        revision = UUID(); paused = false; pause.title = "Pause"
        text.string = "Loading…"; refresh(force: true)
    }
    @objc func togglePause() {
        paused.toggle(); pause.title = paused ? "Resume" : "Pause"
        // Invalidate an in-flight read so Pause really freezes the visible text.
        revision = UUID(); if !paused { refresh(force: true) }
    }
    func refresh(force: Bool = false) {
        guard window.isVisible, !reading, force || !paused, let output else { return }
        let url: URL
        switch source.indexOfSelectedItem {
        case 0: url = output.appendingPathComponent("uart-tx.log")
        case 1: url = output.appendingPathComponent("stderr.log")
        case 2: url = output.deletingLastPathComponent().appendingPathComponent(output.lastPathComponent + ".desktop.log")
        case 9: url = output.appendingPathComponent("plugin-trace.log")
        default: url = output.appendingPathComponent("ex-usart\(source.indexOfSelectedItem - 2)-tx.log")
        }
        reading = true; let expected = revision
        DispatchQueue.global(qos: .utility).async { [weak self] in
            let snapshot = readDiagnosticLog(url)
            DispatchQueue.main.async {
                guard let self else { return }
                self.reading = false
                guard self.revision == expected else { self.refresh(); return }
                if self.text.string != snapshot {
                    self.text.string = snapshot
                    self.text.scrollToEndOfDocument(nil)
                }
            }
        }
    }
}

final class Desktop: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate, WKScriptMessageHandler, NSMenuItemValidation {
    var diagnostics: Diagnostics?
    var window: NSWindow!
    var view: WKWebView!
    var child: Process?
    var baseURL: URL?
    var output: URL?
    var lineBuffer = Data()
    var terminating = false
    var lastError = false
    var modeReady = false
    var captureReady = false
    var dialsReady = false
    var buttonsReady = Set<String>()
    var activeConfiguration: [String: Any]?
    var restartOutputRoot: String?
    var restartURL: URL?
    var starting = false
    var startupID = UUID()
    var checkingPath: String?
    var accessPanelOpen = false
    var pendingAccessCompletion: (() -> Void)?
    var manualInputContinuation: (() -> Void)?
    var inputCheckID = UUID()
    var configurationSnapshot: URL?
    var exporting = false
    var exportCancelled = false
    var exportProcess: Process?
    var exportProgress: NSAlert?

    func applicationDidFinishLaunching(_ notification: Notification) {
        let menu = NSMenu()
        let appItem = NSMenuItem(); menu.addItem(appItem)
        let appMenu = NSMenu(); appItem.submenu = appMenu
        appMenu.addItem(withTitle: "Quit Z8", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        let sessionItem = NSMenuItem(); menu.addItem(sessionItem)
        let sessionMenu = NSMenu(title: "Session"); sessionItem.submenu = sessionMenu
        for (title, selector, key) in [
            ("Open configuration…", #selector(openConfiguration), "o"),
            ("Allow input access…", #selector(allowInputAccess), ""),
            ("Save display…", #selector(saveDisplay), "s"),
            ("Save session log…", #selector(saveSessionLog), ""),
            ("Show diagnostics", #selector(showDiagnostics), "d"),
            ("Export diagnostics…", #selector(exportDiagnostics), ""),
            ("Export photos…", #selector(exportPhotos), ""),
            ("Cancel export", #selector(cancelPhotoExport), ""),
            ("Show session files", #selector(showOutput), ""),
            ("Restart session", #selector(restartSession), "r"),
            ("Stop emulator", #selector(stopSession), ".")
        ] {
            let item = sessionMenu.addItem(withTitle: title, action: selector, keyEquivalent: key)
            item.target = self
            if selector == #selector(restartSession) { item.keyEquivalentModifierMask = [.command, .shift] }
        }
        let cameraItem = NSMenuItem(); menu.addItem(cameraItem)
        let cameraMenu = NSMenu(title: "Camera"); cameraItem.submenu = cameraMenu
        for (title, selector, key) in [
            ("Switch to Photo", #selector(selectPhoto), "1"),
            ("Switch to Movie", #selector(selectMovie), "2"),
            ("Capture photo", #selector(capturePhoto), ""),
            ("MENU", #selector(cameraMenuButton), ""),
            ("Half shutter", #selector(cameraHalfButton), ""),
            ("Playback", #selector(cameraPlayButton), ""),
            ("i menu", #selector(cameraIButton), ""),
            ("DISP", #selector(cameraDispButton), ""),
            ("Main dial −", #selector(mainDialMinus), ""),
            ("Main dial +", #selector(mainDialPlus), ""),
            ("Sub dial −", #selector(subDialMinus), ""),
            ("Sub dial +", #selector(subDialPlus), ""),
            ("Exposure mode −", #selector(exposureModeMinus), ""),
            ("Exposure mode +", #selector(exposureModePlus), ""),
            ("Protect key", #selector(cameraProtectButton), ""),
            ("Delete key", #selector(cameraDeleteButton), ""),
            ("Up", #selector(cameraUpButton), ""),
            ("Down", #selector(cameraDownButton), ""),
            ("Left", #selector(cameraLeftButton), ""),
            ("Right", #selector(cameraRightButton), ""),
            ("OK", #selector(cameraOKButton), "")
        ] {
            let item = cameraMenu.addItem(withTitle: title, action: selector, keyEquivalent: key)
            item.target = self
        }
        NSApp.mainMenu = menu
        let compact = CommandLine.arguments.contains("--compact")
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: compact ? 680 : 1200, height: compact ? 780 : 880),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Z8 emulator"; window.minSize = NSSize(width: 620, height: 640)
        window.delegate = self; window.center()
        let configuration = WKWebViewConfiguration()
        configuration.userContentController.add(self, name: "z8State")
        view = WKWebView(frame: .zero, configuration: configuration); view.navigationDelegate = self
        window.contentView = view
        window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
        message("Open a configuration to start", detail: "Choose Session → Open configuration. Your firmware, sensor input and virtual card stay on this Mac.")
        let arguments = CommandLine.arguments
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            if let at = arguments.firstIndex(of: "--config"), arguments.count > at + 1 {
                self.start(URL(fileURLWithPath: arguments[at + 1]))
            } else {
                self.openConfiguration()
            }
        }
    }

    func escaped(_ text: String) -> String {
        text.replacingOccurrences(of: "&", with: "&amp;").replacingOccurrences(of: "<", with: "&lt;").replacingOccurrences(of: ">", with: "&gt;")
    }
    func message(_ title: String, detail: String) {
        // Startup/error presentation uses the same workbench stylesheet, loaded
        // from its canonical owner by the bundle builder.
        let cssURL = Bundle.main.resourceURL!.appendingPathComponent("workbench.css")
        let css = (try? String(contentsOf: cssURL, encoding: .utf8)) ?? ""
        view.loadHTMLString("<html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>Z8 emulator</title><style>\(css)</style><main><h1>\(escaped(title))</h1><p role='status'>\(escaped(detail))</p></main></html>", baseURL: nil)
    }
    @objc func openConfiguration() {
        guard child == nil && !starting && !exporting else { return }
        let panel = NSOpenPanel(); panel.title = "Open Z8 configuration"
        panel.allowedContentTypes = [.json]; panel.allowsMultipleSelection = false
        if panel.runModal() == .OK, let url = panel.url { start(url) }
    }
    func permissionFailure(_ error: Error) -> Bool {
        let failure = error as NSError, underlying = (error as NSError).userInfo[NSUnderlyingErrorKey] as? NSError
        return failure.code == NSFileReadNoPermissionError ||
            (failure.domain == NSPOSIXErrorDomain && [1, 13].contains(failure.code)) ||
            (underlying?.domain == NSPOSIXErrorDomain && [1, 13].contains(underlying?.code ?? 0))
    }
    func chooseInput(_ path: String) -> Bool {
        let expected = URL(fileURLWithPath: path).standardizedFileURL
        let panel = NSOpenPanel(); panel.title = "Allow access to " + expected.lastPathComponent
        panel.message = "Select this configured input to allow the emulator to read it."
        panel.directoryURL = expected.deletingLastPathComponent()
        panel.nameFieldStringValue = expected.lastPathComponent
        panel.allowsMultipleSelection = false; panel.canChooseDirectories = false
        accessPanelOpen = true
        let accepted = panel.runModal() == .OK && panel.url?.resolvingSymlinksInPath() == expected.resolvingSymlinksInPath()
        accessPanelOpen = false
        let deferred = pendingAccessCompletion; pendingAccessCompletion = nil
        if let deferred { DispatchQueue.main.async(execute: deferred) }
        return accepted
    }
    @objc func allowInputAccess() {
        guard starting, let checkingPath, !accessPanelOpen else { return }
        let resume = manualInputContinuation
        if chooseInput(checkingPath) {
            guard starting, self.checkingPath == checkingPath else { return }
            // The exact native selection grants access even if an earlier
            // filesystem read remains pending. Retire that read's completion.
            inputCheckID = UUID(); manualInputContinuation = nil
            resume?()
        } else { stopSession() }
    }
    func authorizeInputs(_ paths: [String], id: UUID, attempted: Set<String> = [], completion: @escaping (Result<Void, Error>) -> Void) {
        guard starting && startupID == id else { return }
        guard let path = paths.first else { checkingPath = nil; manualInputContinuation = nil; completion(.success(())); return }
        checkingPath = path
        let check = UUID(); inputCheckID = check
        manualInputContinuation = { [weak self] in
            self?.authorizeInputs(Array(paths.dropFirst()), id: id, attempted: attempted.union([path]), completion: completion)
        }
        message("Checking local inputs", detail: "Checking " + URL(fileURLWithPath: path).lastPathComponent + ". If access pauses, choose Session → Allow input access. Stop emulator cancels startup.")
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let result = Result {
                guard path.hasPrefix("/") else {
                    throw NSError(domain: "Z8", code: 4, userInfo: [NSLocalizedDescriptionKey: "Input paths must be absolute."])
                }
                let url = URL(fileURLWithPath: path)
                let attributes = try FileManager.default.attributesOfItem(atPath: url.resolvingSymlinksInPath().path)
                guard attributes[.type] as? FileAttributeType == .typeRegular else {
                    throw NSError(domain: "Z8", code: 5, userInfo: [NSLocalizedDescriptionKey: "Configured inputs must be regular files."])
                }
                let file = try FileHandle(forReadingFrom: url); try file.close()
            }
            DispatchQueue.main.async { [weak self] in
                guard let self else { return }
                let finish = {
                    guard self.starting && self.startupID == id && self.inputCheckID == check else { return }
                    switch result {
                    case .success:
                        self.authorizeInputs(Array(paths.dropFirst()), id: id, attempted: attempted, completion: completion)
                    case .failure(let error):
                        if self.permissionFailure(error) && !attempted.contains(path) {
                            if self.chooseInput(path) {
                                self.authorizeInputs(paths, id: id, attempted: attempted.union([path]), completion: completion)
                            } else {
                                completion(.failure(NSError(domain: NSCocoaErrorDomain, code: NSUserCancelledError)))
                            }
                        } else if self.permissionFailure(error) {
                            let name = URL(fileURLWithPath: path).lastPathComponent
                            completion(.failure(NSError(domain: "Z8", code: 6, userInfo: [NSLocalizedDescriptionKey:
                                "Cannot read configured input “" + name + "”. Check its file permissions."])))
                        } else { completion(.failure(error)) }
                    }
                }
                if self.accessPanelOpen { self.pendingAccessCompletion = finish } else { finish() }
            }
        }
    }
    func cleanupSnapshot(_ url: URL?) {
        if let url { try? FileManager.default.removeItem(at: url) }
        if configurationSnapshot == url { configurationSnapshot = nil }
    }
    func start(_ configuration: URL, restoring: Bool = false) {
        guard child == nil && !starting && !exporting else { return }
        lastError = false; modeReady = false; captureReady = false; dialsReady = false; buttonsReady = []
        do {
            let value = try JSONSerialization.jsonObject(with: Data(contentsOf: configuration))
            guard let config = value as? [String: Any], let python = config["python"] as? String,
                  python.hasPrefix("/"), FileManager.default.isExecutableFile(atPath: python),
                  let out = config["output"] as? String else {
                throw NSError(domain: "Z8", code: 1, userInfo: [NSLocalizedDescriptionKey: "Configuration needs an absolute Python 3.11+ executable and output path."])
            }
            starting = true; let id = UUID(); startupID = id
            let paths = ["firmware", "mcu", "qemu", "raw", "card", "trace_plugin"].compactMap { config[$0] as? String }
            authorizeInputs(paths, id: id) { [weak self] result in
                guard let self, self.starting, self.startupID == id else { return }
                self.starting = false; self.checkingPath = nil
                do {
                    try result.get()
                    try self.launch(config, python: python, out: out, restoring: restoring)
                } catch {
                    self.cleanupSnapshot(self.configurationSnapshot)
                    let failure = error as NSError
                    if failure.domain == NSCocoaErrorDomain && failure.code == NSUserCancelledError {
                        self.message("Startup cancelled", detail: "Choose Session → Open configuration to try again.")
                    } else {
                        self.message("Could not start Z8", detail: error.localizedDescription + " Choose Session → Open configuration to try again.")
                    }
                }
            }
        } catch {
            message("Could not start Z8", detail: error.localizedDescription + " Choose Session → Open configuration to try again.")
        }
    }
    func configurePython(_ process: Process) {
        // Keep the signed runtime immutable, including spawned Python workers.
        var environment = ProcessInfo.processInfo.environment
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        process.environment = environment
    }
    func launch(_ config: [String: Any], python: String, out: String, restoring: Bool) throws {
        output = URL(fileURLWithPath: out); baseURL = nil; lineBuffer = Data()
        diagnostics?.setOutput(output, nativeEX: config["mcu"] is String, trace: config["trace_plugin"] is String)
        let process = Process(); let pipe = Pipe()
        configurePython(process)
        process.executableURL = URL(fileURLWithPath: python)
        let script = Bundle.main.resourceURL!.appendingPathComponent("runtime/tools/desktop_session.py")
        let snapshot = FileManager.default.temporaryDirectory.appendingPathComponent("z8-config-" + UUID().uuidString + ".json")
        configurationSnapshot = snapshot
        try JSONSerialization.data(withJSONObject: config).write(to: snapshot, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: snapshot.path)
        process.arguments = ["-u", script.path, "--config", snapshot.path]
        process.standardOutput = pipe; process.standardError = FileHandle.nullDevice
        pipe.fileHandleForReading.readabilityHandler = { [weak self, weak process] handle in
            let bytes = handle.availableData
            if bytes.isEmpty { handle.readabilityHandler = nil; return }
            DispatchQueue.main.async {
                guard let self, let process, self.child === process else { return }
                self.receive(bytes)
            }
        }
        process.terminationHandler = { [weak self] process in
            DispatchQueue.main.async {
                guard let self else { return }
                self.cleanupSnapshot(snapshot)
                guard self.child === process else { return }
                self.child = nil; self.modeReady = false; self.captureReady = false; self.dialsReady = false; self.buttonsReady = []
                if self.terminating { self.cancelRestart(); NSApp.reply(toApplicationShouldTerminate: true) }
                else if let restart = self.restartURL {
                    self.restartURL = nil
                    self.start(restart, restoring: true)
                    try? FileManager.default.removeItem(at: restart)
                }
                else if process.terminationStatus != 0 && !self.lastError {
                    self.message("Emulator stopped", detail: "Check the session log beside your output folder, then open a corrected configuration.")
                }
            }
        }
        try process.run(); child = process; activeConfiguration = config
        if !restoring { restartOutputRoot = URL(fileURLWithPath: out).standardizedFileURL.path }
        message("Starting Z8", detail: "The original firmware is booting. Camera controls become available when the guest is ready.")
    }
    func receive(_ bytes: Data) {
        lineBuffer.append(bytes)
        while let end = lineBuffer.firstIndex(of: 10) {
            let line = lineBuffer[..<end]; lineBuffer.removeSubrange(...end)
            guard let item = try? JSONSerialization.jsonObject(with: Data(line)) as? [String: Any],
                  let event = item["event"] as? String else { continue }
            if event == "ready", let text = item["url"] as? String, let url = URL(string: text),
               url.scheme == "http", url.host == "127.0.0.1", url.port != nil {
                cleanupSnapshot(configurationSnapshot)
                baseURL = url; view.load(URLRequest(url: url))
            } else if event == "error", let text = item["message"] as? String {
                cleanupSnapshot(configurationSnapshot)
                lastError = true
                message("Could not start Z8", detail: text + " Choose Session → Open configuration to try again.")
            }
        }
    }
    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
        let local = url.absoluteString == "about:blank" ||
            (url.scheme == baseURL?.scheme && url.host == baseURL?.host && url.port == baseURL?.port)
        decisionHandler(local ? .allow : .cancel)
    }
    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.name == "z8State", message.frameInfo.isMainFrame,
              let baseURL, message.frameInfo.securityOrigin.protocol == baseURL.scheme,
              message.frameInfo.securityOrigin.host == baseURL.host,
              message.frameInfo.securityOrigin.port == baseURL.port,
              let value = message.body as? [String: Any], let ready = value["modeReady"] as? Bool else { return }
        modeReady = ready
        captureReady = value["captureReady"] as? Bool ?? false
        dialsReady = value["dialsReady"] as? Bool ?? false
        buttonsReady = Set((value["buttonsReady"] as? [String] ?? []).filter { cameraButtonActions.values.contains($0) })
    }
    func selectMode(_ mode: String) {
        guard modeReady, child?.isRunning == true, baseURL != nil,
              mode == "photo" || mode == "movie" else { return }
        view.evaluateJavaScript("window.z8Workbench?.selectMode('\(mode)')")
    }
    @objc func capturePhoto() {
        guard captureReady, child?.isRunning == true, baseURL != nil else { return }
        view.evaluateJavaScript("window.z8Workbench?.capturePhoto()")
    }
    var dialActions: [Selector: (String, Int)] {
        [#selector(mainDialMinus): ("main", -1), #selector(mainDialPlus): ("main", 1),
         #selector(subDialMinus): ("sub", -1), #selector(subDialPlus): ("sub", 1),
         #selector(exposureModeMinus): ("mode", -1), #selector(exposureModePlus): ("mode", 1)]
    }
    func turnDial(_ axis: String, _ direction: Int) {
        guard dialsReady, child?.isRunning == true, baseURL != nil,
              ["main", "sub", "mode"].contains(axis), [-1, 1].contains(direction) else { return }
        view.evaluateJavaScript("window.z8Workbench?.turnDial('\(axis)',\(direction))")
    }
    @objc func mainDialMinus() { turnDial("main", -1) }
    @objc func mainDialPlus() { turnDial("main", 1) }
    @objc func subDialMinus() { turnDial("sub", -1) }
    @objc func subDialPlus() { turnDial("sub", 1) }
    @objc func exposureModeMinus() { turnDial("mode", -1) }
    @objc func exposureModePlus() { turnDial("mode", 1) }
    var cameraButtonActions: [Selector: String] {
        [#selector(cameraMenuButton): "menu", #selector(cameraHalfButton): "half",
         #selector(cameraPlayButton): "play", #selector(cameraIButton): "i", #selector(cameraDispButton): "disp",
         #selector(cameraProtectButton): "protect", #selector(cameraDeleteButton): "delete",
         #selector(cameraUpButton): "up", #selector(cameraDownButton): "down",
         #selector(cameraLeftButton): "left", #selector(cameraRightButton): "right", #selector(cameraOKButton): "ok"]
    }
    func pressCameraButton(_ key: String) {
        guard buttonsReady.contains(key), child?.isRunning == true, baseURL != nil else { return }
        view.evaluateJavaScript("window.z8Workbench?.press('\(key)')")
    }
    @objc func cameraMenuButton() { pressCameraButton("menu") }
    @objc func cameraHalfButton() { pressCameraButton("half") }
    @objc func cameraPlayButton() { pressCameraButton("play") }
    @objc func cameraIButton() { pressCameraButton("i") }
    @objc func cameraDispButton() { pressCameraButton("disp") }
    @objc func cameraProtectButton() { pressCameraButton("protect") }
    @objc func cameraDeleteButton() { pressCameraButton("delete") }
    @objc func cameraUpButton() { pressCameraButton("up") }
    @objc func cameraDownButton() { pressCameraButton("down") }
    @objc func cameraLeftButton() { pressCameraButton("left") }
    @objc func cameraRightButton() { pressCameraButton("right") }
    @objc func cameraOKButton() { pressCameraButton("ok") }
    @objc func showDiagnostics() {
        if diagnostics == nil { diagnostics = Diagnostics(); diagnostics?.setOutput(output, nativeEX: activeConfiguration?["mcu"] is String, trace: activeConfiguration?["trace_plugin"] is String) }
        diagnostics?.show()
    }
    @objc func selectPhoto() { selectMode("photo") }
    @objc func selectMovie() { selectMode("movie") }
    @objc func saveDisplay() {
        guard let baseURL else { return }
        let panel = NSSavePanel(); panel.nameFieldStringValue = "Z8-display.png"; panel.allowedContentTypes = [.png]
        guard panel.runModal() == .OK, let destination = panel.url else { return }
        URLSession.shared.dataTask(with: baseURL.appendingPathComponent("frame.png")) { data, response, error in
            do {
                guard let data, (response as? HTTPURLResponse)?.statusCode == 200, error == nil else {
                    throw NSError(domain: "Z8", code: 2, userInfo: [NSLocalizedDescriptionKey: "No camera display is available yet."])
                }
                try data.write(to: destination, options: .atomic)
            } catch {
                DispatchQueue.main.async {
                    let alert = NSAlert(); alert.messageText = "Could not save display"; alert.informativeText = error.localizedDescription
                    alert.beginSheetModal(for: self.window)
                }
            }
        }.resume()
    }
    @objc func saveSessionLog() {
        guard let output, child == nil, !starting, !exporting else { return }
        let source = output.deletingLastPathComponent().appendingPathComponent(output.lastPathComponent + ".desktop.log")
        let panel = NSSavePanel(); panel.nameFieldStringValue = "Z8-session.log"
        guard panel.runModal() == .OK, let destination = panel.url else { return }
        DispatchQueue.global(qos: .userInitiated).async {
            do {
                guard destination.resolvingSymlinksInPath() != source.resolvingSymlinksInPath() else {
                    throw NSError(domain: "Z8", code: 7, userInfo: [NSLocalizedDescriptionKey: "Choose a different destination for the exported log."])
                }
                try Data(contentsOf: source).write(to: destination, options: .atomic)
            } catch {
                DispatchQueue.main.async {
                    let alert = NSAlert(); alert.messageText = "Could not save session log"; alert.informativeText = error.localizedDescription
                    alert.beginSheetModal(for: self.window)
                }
            }
        }
    }
    @objc func exportPhotos() {
        guard child == nil, !starting, !exporting, let output,
              let card = activeConfiguration?["card"] as? String,
              let python = activeConfiguration?["python"] as? String else { return }
        let panel = NSSavePanel()
        panel.title = "Export photos"; panel.prompt = "Export"
        panel.message = "Copy the photos on this virtual card into a new folder."
        panel.nameFieldLabel = "Folder name:"; panel.nameFieldStringValue = "Z8 photos"
        panel.canCreateDirectories = true
        guard panel.runModal() == .OK, let destination = panel.url else { return }
        // Native dialogs own destination selection; the helper verifies stopped
        // ownership, holds QEMU-compatible card locks and publishes atomically.
        runExport(python: python, script: "desktop_photo_export.py", arguments: ["--card", card, "--session", output.path, "--output", destination.path], destination: destination, diagnostics: false)
    }
    @objc func exportDiagnostics() {
        guard child == nil, !starting, !exporting, let output,
              let python = activeConfiguration?["python"] as? String else { return }
        let panel = NSSavePanel(); panel.title = "Export diagnostics"; panel.prompt = "Export"
        panel.allowedContentTypes = [.zip]; panel.nameFieldStringValue = "Z8-diagnostics.zip"
        panel.message = "Save UART, QEMU, launcher and plugin logs. Logs may contain private paths or memory values; review before sharing."
        guard panel.runModal() == .OK, let destination = panel.url else { return }
        runExport(python: python, script: "desktop_log_export.py", arguments: ["--session", output.path, "--output", destination.path], destination: destination, diagnostics: true)
    }
    func runExport(python: String, script: String, arguments: [String], destination: URL, diagnostics: Bool) {
        let process = Process(), pipe = Pipe()
        configurePython(process)
        process.executableURL = URL(fileURLWithPath: python)
        process.arguments = [Bundle.main.resourceURL!.appendingPathComponent("runtime/tools/" + script).path] + arguments
        process.standardOutput = pipe; process.standardError = pipe
        let operation = diagnostics ? "diagnostics" : "photos"
        exporting = true; exportCancelled = false; exportProcess = process
        do {
            try process.run()
            let progress = NSAlert(); progress.messageText = "Exporting " + operation
            progress.informativeText = "Saving to “" + destination.lastPathComponent + "”."
            progress.addButton(withTitle: "Cancel export").keyEquivalent = "\u{1b}"
            let spinner = NSProgressIndicator(frame: NSRect(x: 0, y: 0, width: 32, height: 32))
            spinner.style = .spinning; spinner.startAnimation(nil)
            spinner.setAccessibilityLabel("Exporting " + operation)
            progress.accessoryView = spinner; exportProgress = progress
            progress.beginSheetModal(for: window) { [weak self] response in
                if response == .alertFirstButtonReturn { self?.cancelPhotoExport() }
            }
            DispatchQueue.global(qos: .userInitiated).async { [weak self] in
                let data = pipe.fileHandleForReading.readDataToEndOfFile()
                process.waitUntilExit()
                let result = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
                DispatchQueue.main.async { [weak self] in
                    guard let self, self.exportProcess === process else { return }
                    self.exportProcess = nil; self.exporting = false
                    if let progress = self.exportProgress { self.window.endSheet(progress.window, returnCode: .abort) }
                    self.exportProgress = nil
                    if self.terminating { NSApp.reply(toApplicationShouldTerminate: true); return }
                    let alert = NSAlert()
                    if self.exportCancelled {
                        alert.messageText = diagnostics ? "Diagnostic export cancelled" : "Photo export cancelled"
                        alert.informativeText = "Check the destination before trying again. Existing files were not replaced."
                    } else if process.terminationStatus == 0, result?["ok"] as? Bool == true,
                              let count = result?["count"] as? Int {
                        alert.messageText = diagnostics ? "Exported \(count) diagnostic logs" : (count == 1 ? "Exported 1 photo" : "Exported \(count) photos")
                        alert.informativeText = destination.path
                        alert.addButton(withTitle: "Done")
                        alert.addButton(withTitle: "Show in Finder")
                        alert.beginSheetModal(for: self.window) { response in
                            if response == .alertSecondButtonReturn {
                                if diagnostics { NSWorkspace.shared.activateFileViewerSelecting([destination]) }
                                else { NSWorkspace.shared.open(destination) }
                            }
                        }
                        return
                    } else {
                        alert.messageText = "Could not export " + operation
                        alert.informativeText = result?["message"] as? String ?? (diagnostics ? "Check the stopped session and destination, then try again." : "Check the destination and card, then try again.")
                    }
                    alert.beginSheetModal(for: self.window)
                }
            }
        } catch {
            exporting = false; exportProcess = nil
            let alert = NSAlert(); alert.messageText = "Could not export " + operation; alert.informativeText = error.localizedDescription
            alert.beginSheetModal(for: window)
        }
    }
    @objc func cancelPhotoExport() {
        guard exporting, exportProcess?.isRunning == true else { return }
        exportCancelled = true; exportProcess?.terminate()
    }
    @objc func showOutput() { if let output { NSWorkspace.shared.selectFile(output.path, inFileViewerRootedAtPath: output.deletingLastPathComponent().path) } }
    func cancelRestart() {
        if let restartURL { try? FileManager.default.removeItem(at: restartURL) }
        restartURL = nil
    }
    func terminateChild() { if let child, child.isRunning { child.terminate() } }
    @objc func stopSession() {
        cancelRestart()
        if starting {
            startupID = UUID(); inputCheckID = UUID(); starting = false; checkingPath = nil
            pendingAccessCompletion = nil; manualInputContinuation = nil
            if !terminating { message("Startup cancelled", detail: "Choose Session → Open configuration to try again.") }
        }
        terminateChild()
    }
    @objc func restartSession() {
        guard var configuration = activeConfiguration, !terminating, !starting, !exporting, restartURL == nil,
              let originalOutput = restartOutputRoot ?? configuration["output"] as? String else { return }
        let suffix = UUID().uuidString.lowercased()
        configuration["output"] = originalOutput + "-restart-" + String(suffix.prefix(8))
        let temporary = FileManager.default.temporaryDirectory.appendingPathComponent("z8-restart-" + suffix + ".json")
        do {
            try JSONSerialization.data(withJSONObject: configuration).write(to: temporary, options: .atomic)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: temporary.path)
            if child != nil {
                restartURL = temporary; modeReady = false; captureReady = false; dialsReady = false; terminateChild()
            } else {
                start(temporary, restoring: true)
                try? FileManager.default.removeItem(at: temporary)
            }
        } catch {
            try? FileManager.default.removeItem(at: temporary)
            let alert = NSAlert(); alert.messageText = "Could not restart Z8"; alert.informativeText = error.localizedDescription
            alert.beginSheetModal(for: window)
        }
    }
    func validateMenuItem(_ item: NSMenuItem) -> Bool {
        if let action = item.action, dialActions[action] != nil { return dialsReady && child?.isRunning == true && baseURL != nil }
        if let action = item.action, let key = cameraButtonActions[action] { return buttonsReady.contains(key) && child?.isRunning == true && baseURL != nil }
        if item.action == #selector(capturePhoto) { return captureReady && child?.isRunning == true && baseURL != nil }
        if item.action == #selector(selectPhoto) || item.action == #selector(selectMovie) { return modeReady && child?.isRunning == true && baseURL != nil }
        if item.action == #selector(exportDiagnostics) { return activeConfiguration?["python"] is String && output != nil && child == nil && !starting && !exporting }
        if item.action == #selector(exportPhotos) { return activeConfiguration?["card"] is String && output != nil && child == nil && !starting && !exporting }
        if item.action == #selector(cancelPhotoExport) { return exporting && !exportCancelled }
        if item.action == #selector(openConfiguration) { return child == nil && !starting && !exporting && restartURL == nil }
        if item.action == #selector(restartSession) { return activeConfiguration != nil && !terminating && !starting && !exporting && restartURL == nil }
        if item.action == #selector(allowInputAccess) { return starting && checkingPath != nil && !accessPanelOpen }
        if item.action == #selector(saveDisplay) { return child != nil && baseURL != nil }
        if item.action == #selector(saveSessionLog) { return output != nil && child == nil && !starting && !exporting }
        if item.action == #selector(stopSession) { return child != nil || starting }
        return output != nil
    }
    func windowShouldClose(_ sender: NSWindow) -> Bool { NSApp.terminate(nil); return false }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        terminating = true; stopSession(); cancelPhotoExport(); cleanupSnapshot(configurationSnapshot)
        guard child != nil || exporting else { return .terminateNow }
        return .terminateLater
    }
}

let application = NSApplication.shared
let delegate = Desktop()
application.delegate = delegate
application.setActivationPolicy(.regular)
application.run()
