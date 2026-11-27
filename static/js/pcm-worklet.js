// AudioWorklet: microphone float samples (usually 48 kHz) -> 16 kHz mono 16-bit PCM, 100 ms per message.
// Downsampling averages the input samples that fall into each output sample (a simple low-pass),
// with a fractional phase so non-integer ratios like 44.1k -> 16k stay in sync.
const TARGET_RATE = 16000;
const CHUNK_SAMPLES = 1600; // 100 ms at 16 kHz

class PcmCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / TARGET_RATE; // `sampleRate` is a global in the worklet scope
    this.phase = 0;
    this.sum = 0;
    this.count = 0;
    this.buffer = new Int16Array(CHUNK_SAMPLES);
    this.offset = 0;
    this.sumSquares = 0;
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel) return true;

    for (let i = 0; i < channel.length; i++) {
      this.sum += channel[i];
      this.count += 1;
      this.phase += 1;
      if (this.phase >= this.ratio) {
        this.phase -= this.ratio;
        let v = this.sum / this.count;
        this.sum = 0;
        this.count = 0;
        v = Math.max(-1, Math.min(1, v));
        this.sumSquares += v * v;
        this.buffer[this.offset++] = v < 0 ? v * 0x8000 : v * 0x7fff;
        if (this.offset === CHUNK_SAMPLES) {
          const level = Math.sqrt(this.sumSquares / CHUNK_SAMPLES);
          this.port.postMessage({ pcm: this.buffer.buffer, level }, [this.buffer.buffer]);
          this.buffer = new Int16Array(CHUNK_SAMPLES);
          this.offset = 0;
          this.sumSquares = 0;
        }
      }
    }
    return true;
  }
}

registerProcessor("pcm-capture", PcmCaptureProcessor);
