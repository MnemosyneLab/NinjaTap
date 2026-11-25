import AppKit
import Foundation
import Vision

let arguments = CommandLine.arguments
if arguments.count != 2 {
    fputs("usage: recognize image.png\n", stderr)
    exit(2)
}

let url = URL(fileURLWithPath: arguments[1])
guard let image = NSImage(contentsOf: url),
      let tiff = image.tiffRepresentation,
      let rep = NSBitmapImageRep(data: tiff) else {
    fputs("unreadable image\n", stderr)
    exit(1)
}

let width = CGFloat(rep.pixelsWide)
let height = CGFloat(rep.pixelsHigh)
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
// English first makes Vision read the whole frame as Latin, so Chinese
// comes back as garbage. Chinese has to be the first language.
request.recognitionLanguages = ["zh-Hans", "en-US"]
request.usesLanguageCorrection = true

let handler = VNImageRequestHandler(url: url)
do {
    try handler.perform([request])
} catch {
    fputs("\(error)\n", stderr)
    exit(1)
}

var items: [[String: Any]] = []
for observation in request.results ?? [] {
    guard let candidate = observation.topCandidates(1).first, candidate.confidence >= 0.3 else {
        continue
    }
    let box = observation.boundingBox
    let x = Int((box.origin.x * width).rounded())
    let y = Int(((1 - box.origin.y - box.size.height) * height).rounded())
    let w = Int((box.size.width * width).rounded())
    let h = Int((box.size.height * height).rounded())
    items.append(["text": candidate.string, "x": x, "y": y, "w": max(w, 1), "h": max(h, 1)])
}

let data = try JSONSerialization.data(withJSONObject: items)
FileHandle.standardOutput.write(data)
