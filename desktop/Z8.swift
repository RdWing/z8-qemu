// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 RdWing
import AppKit
import WebKit

final class Desktop: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate {
    var window: NSWindow!
    var view: WKWebView!
    var child: Process?
    var baseURL: URL?
    var output: URL?
    var lineBuffer = Data()
    var terminating = false
    var lastError = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        let menu = NSMenu()
        let appItem = NSMenuItem(); menu.addItem(appItem)
        let appMenu = NSMenu(); appItem.submenu = appMenu
        appMenu.addItem(withTitle: "Quit Z8", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        let sessionItem = NSMenuItem(); menu.addItem(sessionItem)
        let sessionMenu = NSMenu(title: "Session"); sessionItem.submenu = sessionMenu
        for (title, selector, key) in [
            ("Open configuration…", #selector(openConfiguration), "o"),
            ("Save display…", #selector(saveDisplay), "s"),
            ("Show session files", #selector(showOutput), ""),
            ("Stop emulator", #selector(stopSession), ".")
        ] {
            let item = sessionMenu.addItem(withTitle: title, action: selector, keyEquivalent: key)
            item.target = self
        }
        NSApp.mainMenu = menu
        let compact = CommandLine.arguments.contains("--compact")
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: compact ? 680 : 1200, height: compact ? 780 : 880),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Z8 emulator"; window.minSize = NSSize(width: 620, height: 640)
        window.delegate = self; window.center()
        view = WKWebView(frame: .zero); view.navigationDelegate = self
        window.contentView = view
        window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
        message("Open a configuration to start", detail: "Choose Session → Open configuration. Your firmware, sensor input and virtual card stay on this Mac.")
        let arguments = CommandLine.arguments
        if let at = arguments.firstIndex(of: "--config"), arguments.count > at + 1 {
            start(URL(fileURLWithPath: arguments[at + 1]))
        } else {
            openConfiguration()
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
        guard child == nil else { return }
        let panel = NSOpenPanel(); panel.title = "Open Z8 configuration"
        panel.allowedContentTypes = [.json]; panel.allowsMultipleSelection = false
        if panel.runModal() == .OK, let url = panel.url { start(url) }
    }
    func start(_ configuration: URL) {
        guard child == nil else { return }
        lastError = false
        do {
            let value = try JSONSerialization.jsonObject(with: Data(contentsOf: configuration))
            guard let config = value as? [String: Any], let python = config["python"] as? String,
                  python.hasPrefix("/"), FileManager.default.isExecutableFile(atPath: python),
                  let out = config["output"] as? String else {
                throw NSError(domain: "Z8", code: 1, userInfo: [NSLocalizedDescriptionKey: "Configuration needs an absolute Python 3.11+ executable and output path."])
            }
            output = URL(fileURLWithPath: out); baseURL = nil; lineBuffer = Data()
            let process = Process(); let pipe = Pipe()
            process.executableURL = URL(fileURLWithPath: python)
            let script = Bundle.main.resourceURL!.appendingPathComponent("runtime/tools/desktop_session.py")
            process.arguments = ["-u", script.path, "--config", configuration.path]
            process.standardOutput = pipe; process.standardError = FileHandle.nullDevice
            pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
                let bytes = handle.availableData
                if bytes.isEmpty { handle.readabilityHandler = nil; return }
                DispatchQueue.main.async { self?.receive(bytes) }
            }
            process.terminationHandler = { [weak self] process in
                DispatchQueue.main.async {
                    guard let self else { return }
                    self.child = nil
                    if self.terminating { NSApp.reply(toApplicationShouldTerminate: true) }
                    else if process.terminationStatus != 0 && !self.lastError {
                        self.message("Emulator stopped", detail: "Check the session log beside your output folder, then open a corrected configuration.")
                    }
                }
            }
            try process.run(); child = process
            message("Starting Z8", detail: "The original firmware is booting. Camera controls become available when the guest is ready.")
        } catch {
            message("Could not start Z8", detail: error.localizedDescription + " Choose Session → Open configuration to try again.")
        }
    }
    func receive(_ bytes: Data) {
        lineBuffer.append(bytes)
        while let end = lineBuffer.firstIndex(of: 10) {
            let line = lineBuffer[..<end]; lineBuffer.removeSubrange(...end)
            guard let item = try? JSONSerialization.jsonObject(with: Data(line)) as? [String: Any],
                  let event = item["event"] as? String else { continue }
            if event == "ready", let text = item["url"] as? String, let url = URL(string: text),
               url.scheme == "http", url.host == "127.0.0.1", url.port != nil {
                baseURL = url; view.load(URLRequest(url: url))
            } else if event == "error", let text = item["message"] as? String {
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
    @objc func showOutput() { if let output { NSWorkspace.shared.selectFile(output.path, inFileViewerRootedAtPath: output.deletingLastPathComponent().path) } }
    @objc func stopSession() { if let child, child.isRunning { child.terminate() } }
    func validateMenuItem(_ item: NSMenuItem) -> Bool {
        if item.action == #selector(openConfiguration) { return child == nil }
        if item.action == #selector(saveDisplay) { return child != nil && baseURL != nil }
        if item.action == #selector(stopSession) { return child != nil }
        return output != nil
    }
    func windowShouldClose(_ sender: NSWindow) -> Bool { NSApp.terminate(nil); return false }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard child != nil else { return .terminateNow }
        terminating = true; stopSession(); return .terminateLater
    }
}

let application = NSApplication.shared
let delegate = Desktop()
application.delegate = delegate
application.setActivationPolicy(.regular)
application.run()
