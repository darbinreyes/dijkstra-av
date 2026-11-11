import AVFoundation
import Foundation

// Write one mono 24 kHz slice of an audio file.
// usage: extract_slice input start_sec duration_sec out.wav

let args = CommandLine.arguments
guard args.count == 5 else {
    fputs("usage: extract_slice input start_sec duration_sec out.wav\n", stderr)
    exit(1)
}
let path = args[1]
let start = Double(args[2])!
let dur = Double(args[3])!
let outPath = args[4]
let sampleRate = 24000

let asset = AVURLAsset(url: URL(fileURLWithPath: path))
let sem = DispatchSemaphore(value: 0)
var tracks: [AVAssetTrack] = []
asset.loadTracks(withMediaType: .audio) { found, _ in
    tracks = found ?? []
    sem.signal()
}
sem.wait()
guard let track = tracks.first else {
    fputs("no audio track\n", stderr)
    exit(2)
}

let reader = try AVAssetReader(asset: asset)
let settings: [String: Any] = [
    AVFormatIDKey: kAudioFormatLinearPCM,
    AVSampleRateKey: sampleRate,
    AVNumberOfChannelsKey: 1,
    AVLinearPCMBitDepthKey: 16,
    AVLinearPCMIsFloatKey: false,
    AVLinearPCMIsBigEndianKey: false,
    AVLinearPCMIsNonInterleaved: false
]
let output = AVAssetReaderTrackOutput(track: track, outputSettings: settings)
reader.add(output)
reader.timeRange = CMTimeRange(
    start: CMTime(seconds: start, preferredTimescale: 24000),
    duration: CMTime(seconds: dur, preferredTimescale: 24000)
)
guard reader.startReading() else {
    fputs("reader failed \(reader.error?.localizedDescription ?? "")\n", stderr)
    exit(3)
}

var pcm = Data()
let cap = sampleRate * 2 * Int(dur + 1.5)
while let sampleBuffer = output.copyNextSampleBuffer() {
    guard let block = CMSampleBufferGetDataBuffer(sampleBuffer) else { continue }
    let len = CMBlockBufferGetDataLength(block)
    var chunk = Data(count: len)
    chunk.withUnsafeMutableBytes { raw in
        _ = CMBlockBufferCopyDataBytes(
            block,
            atOffset: 0,
            dataLength: len,
            destination: raw.baseAddress!
        )
    }
    pcm.append(chunk)
    if pcm.count >= cap { break }
}

func le32(_ n: UInt32) -> [UInt8] {
    [UInt8(n & 0xff), UInt8((n >> 8) & 0xff), UInt8((n >> 16) & 0xff), UInt8((n >> 24) & 0xff)]
}
func le16(_ n: UInt16) -> [UInt8] {
    [UInt8(n & 0xff), UInt8((n >> 8) & 0xff)]
}

let dataSize = UInt32(pcm.count)
var header = Data()
header.append(contentsOf: Array("RIFF".utf8))
header.append(contentsOf: le32(36 + dataSize))
header.append(contentsOf: Array("WAVEfmt ".utf8))
header.append(contentsOf: le32(16))
header.append(contentsOf: le16(1))
header.append(contentsOf: le16(1))
header.append(contentsOf: le32(UInt32(sampleRate)))
header.append(contentsOf: le32(UInt32(sampleRate * 2)))
header.append(contentsOf: le16(2))
header.append(contentsOf: le16(16))
header.append(contentsOf: Array("data".utf8))
header.append(contentsOf: le32(dataSize))
var wav = header
wav.append(pcm)
try wav.write(to: URL(fileURLWithPath: outPath))
print("wrote \(pcm.count / 2) samples, \(Double(pcm.count / 2) / Double(sampleRate)) sec")
