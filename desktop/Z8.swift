// SPDX-License-Identifier: GPL-2.0-or-later
// Copyright (C) 2026 RdWing
import AppKit
import WebKit

final class Desktop: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate, WKScriptMessageHandler, NSMenuItemValidation {
    var window: NSWindow!
    var view: WKWebView!
    var child: Process?
    var baseURL: URL?
    var output: URL?
    var lineBuffer = Data()
    var terminating = false
    var lastError = false
    var modeReady = false
    var activeConfiguration: [String: Any]?
    var restartOutputRoot: String?
    var restartURL: URL?
    var starting = false
    var startupID = UUID()
    var checkingPath: String?
    var accessPanelOpen = false
    var pendingAccessCompletion: (() -> Void)?
    var configurationSnapshot: URL?

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
            ("Switch to Movie", #selector(selectMovie), "2")
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
        guard child == nil && !starting else { return }
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
        if !chooseInput(checkingPath) { stopSession() }
    }
    func authorizeInputs(_ paths: [String], id: UUID, attempted: Set<String> = [], completion: @escaping (Result<Void, Error>) -> Void) {
        guard starting && startupID == id else { return }
        guard let path = paths.first else { checkingPath = nil; completion(.success(())); return }
        checkingPath = path
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
                    guard self.starting && self.startupID == id else { return }
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
        guard child == nil && !starting else { return }
        lastError = false; modeReady = false
        do {
            let value = try JSONSerialization.jsonObject(with: Data(contentsOf: configuration))
            guard let config = value as? [String: Any], let python = config["python"] as? String,
                  python.hasPrefix("/"), FileManager.default.isExecutableFile(atPath: python),
                  let out = config["output"] as? String else {
                throw NSError(domain: "Z8", code: 1, userInfo: [NSLocalizedDescriptionKey: "Configuration needs an absolute Python 3.11+ executable and output path."])
            }
            starting = true; let id = UUID(); startupID = id
            let paths = ["firmware", "mcu", "qemu", "raw", "card"].compactMap { config[$0] as? String }
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
    func launch(_ config: [String: Any], python: String, out: String, restoring: Bool) throws {
        output = URL(fileURLWithPath: out); baseURL = nil; lineBuffer = Data()
        let process = Process(); let pipe = Pipe()
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
                self.child = nil; self.modeReady = false
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
    }
    func selectMode(_ mode: String) {
        guard modeReady, child?.isRunning == true, baseURL != nil,
              mode == "photo" || mode == "movie" else { return }
        view.evaluateJavaScript("window.z8Workbench?.selectMode('\(mode)')")
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
        guard let output, child == nil, !starting else { return }
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
    @objc func showOutput() { if let output { NSWorkspace.shared.selectFile(output.path, inFileViewerRootedAtPath: output.deletingLastPathComponent().path) } }
    func cancelRestart() {
        if let restartURL { try? FileManager.default.removeItem(at: restartURL) }
        restartURL = nil
    }
    func terminateChild() { if let child, child.isRunning { child.terminate() } }
    @objc func stopSession() {
        cancelRestart()
        if starting {
            startupID = UUID(); starting = false; checkingPath = nil; pendingAccessCompletion = nil
            if !terminating { message("Startup cancelled", detail: "Choose Session → Open configuration to try again.") }
        }
        terminateChild()
    }
    @objc func restartSession() {
        guard var configuration = activeConfiguration, !terminating, !starting, restartURL == nil,
              let originalOutput = restartOutputRoot ?? configuration["output"] as? String else { return }
        let suffix = UUID().uuidString.lowercased()
        configuration["output"] = originalOutput + "-restart-" + String(suffix.prefix(8))
        let temporary = FileManager.default.temporaryDirectory.appendingPathComponent("z8-restart-" + suffix + ".json")
        do {
            try JSONSerialization.data(withJSONObject: configuration).write(to: temporary, options: .atomic)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: temporary.path)
            if child != nil {
                restartURL = temporary; modeReady = false; terminateChild()
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
        if item.action == #selector(selectPhoto) || item.action == #selector(selectMovie) { return modeReady && child?.isRunning == true && baseURL != nil }
        if item.action == #selector(openConfiguration) { return child == nil && !starting && restartURL == nil }
        if item.action == #selector(restartSession) { return activeConfiguration != nil && !terminating && !starting && restartURL == nil }
        if item.action == #selector(allowInputAccess) { return starting && checkingPath != nil && !accessPanelOpen }
        if item.action == #selector(saveDisplay) { return child != nil && baseURL != nil }
        if item.action == #selector(saveSessionLog) { return output != nil && child == nil && !starting }
        if item.action == #selector(stopSession) { return child != nil || starting }
        return output != nil
    }
    func windowShouldClose(_ sender: NSWindow) -> Bool { NSApp.terminate(nil); return false }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        terminating = true; stopSession(); cleanupSnapshot(configurationSnapshot)
        guard child != nil else { return .terminateNow }
        return .terminateLater
    }
}

let application = NSApplication.shared
let delegate = Desktop()
application.delegate = delegate
application.setActivationPolicy(.regular)
application.run()
