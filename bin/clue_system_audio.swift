import Foundation
import ScreenCaptureKit
import AVFoundation

// Clue System Audio Capturer
// Captures system-wide audio (Zoom, Google Meet, YouTube, interviewer audio)
// and streams 16kHz 16-bit signed mono PCM to stdout.

@available(macOS 13.0, *)
class SystemAudioPipe: NSObject, SCStreamOutput, SCStreamDelegate {
    let stdoutHandle = FileHandle.standardOutput

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of outputType: SCStreamOutputType) {
        guard outputType == .audio, sampleBuffer.isValid else { return }

        var blockBuffer: CMBlockBuffer?
        var audioBufferList = AudioBufferList()

        let status = CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
            sampleBuffer,
            bufferListSizeNeededOut: nil,
            bufferListOut: &audioBufferList,
            bufferListSize: MemoryLayout<AudioBufferList>.size,
            blockBufferAllocator: nil,
            blockBufferMemoryAllocator: nil,
            flags: 0,
            blockBufferOut: &blockBuffer
        )

        guard status == noErr, let bufferData = audioBufferList.mBuffers.mData else { return }
        let byteSize = Int(audioBufferList.mBuffers.mDataByteSize)
        guard byteSize > 0 else { return }

        let sampleCount = byteSize / MemoryLayout<Float32>.size
        let floatPtr = bufferData.bindMemory(to: Float32.self, capacity: sampleCount)

        var int16Data = [Int16](repeating: 0, count: sampleCount)
        for i in 0..<sampleCount {
            let sample = max(-1.0, min(1.0, floatPtr[i]))
            int16Data[i] = Int16(sample * 32767.0)
        }

        int16Data.withUnsafeBytes { rawBuffer in
            stdoutHandle.write(Data(rawBuffer))
        }
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        fputs("System audio stream error: \(error.localizedDescription)\n", stderr)
        exit(1)
    }
}

func main() {
    guard #available(macOS 13.0, *) else {
        fputs("ScreenCaptureKit requires macOS 13+\n", stderr)
        exit(2)
    }

    // Set up signal handling
    signal(SIGINT) { _ in exit(0) }
    signal(SIGTERM) { _ in exit(0) }
    signal(SIGPIPE) { _ in exit(0) }

    let semaphore = DispatchSemaphore(value: 0)

    Task {
        do {
            let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
            guard let display = content.displays.first else {
                fputs("No display found for ScreenCaptureKit\n", stderr)
                exit(1)
            }

            let filter = SCContentFilter(display: display, excludingApplications: [], exceptingWindows: [])
            let config = SCStreamConfiguration()
            config.capturesAudio = true
            config.sampleRate = 16000
            config.channelCount = 1

            let stream = SCStream(filter: filter, configuration: config, delegate: nil)
            let pipe = SystemAudioPipe()
            try stream.addStreamOutput(pipe, type: .audio, sampleHandlerQueue: DispatchQueue.global(qos: .userInteractive))
            try await stream.startCapture()
            fputs("CLUE_SYSTEM_AUDIO_READY\n", stderr)
        } catch {
            fputs("Failed to initialize ScreenCaptureKit audio: \(error.localizedDescription)\n", stderr)
            exit(1)
        }
    }

    RunLoop.main.run()
}

main()
