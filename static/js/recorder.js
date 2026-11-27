// Captures the microphone and streams 16 kHz PCM over a WebSocket to /ws/transcribe.
// Emits: "state" {state}, "ready" {provider, model, maxSeconds}, "interim" {text},
//        "final" {text, transcript}, "saved" {transcription}, "empty", "info"/"error" {message}, "level" {level}
export class LiveRecorder extends EventTarget {
  constructor() {
    super();
    this.state = "idle"; // idle | connecting | recording | finishing
    this.analyser = null;
  }

  emit(type, detail = {}) {
    this.dispatchEvent(new CustomEvent(type, { detail }));
  }

  setState(state) {
    this.state = state;
    this.emit("state", { state });
  }

  async start({ language = "auto", title = "" } = {}) {
    if (this.state !== "idle") return;
    this.setState("connecting");
    this.pending = [];
    this.started = false;
    this.finished = false;
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    } catch (err) {
      this.setState("idle");
      throw new Error(err && err.name === "NotAllowedError"
        ? "Microphone permission was denied. Allow it in the browser's address bar and try again."
        : `Could not open the microphone: ${err.message || err}`);
    }

    this.ctx = new AudioContext();
    await this.ctx.audioWorklet.addModule("/js/pcm-worklet.js");
    const source = this.ctx.createMediaStreamSource(this.stream);
    this.analyser = this.ctx.createAnalyser();
    this.analyser.fftSize = 1024;
    this.analyser.smoothingTimeConstant = 0.6;
    this.node = new AudioWorkletNode(this.ctx, "pcm-capture");
    const mute = this.ctx.createGain();
    mute.gain.value = 0; // keep the graph pulled without playing the mic back
    source.connect(this.analyser);
    source.connect(this.node).connect(mute).connect(this.ctx.destination);

    this.node.port.onmessage = ({ data }) => {
      this.emit("level", { level: data.level });
      if (this.ws && this.ws.readyState === WebSocket.OPEN && this.started) {
        this.ws.send(data.pcm);
      } else {
        this.pending.push(data.pcm); // speech before the socket opened is not lost
      }
    };

    const scheme = location.protocol === "https:" ? "wss" : "ws";
    this.ws = new WebSocket(`${scheme}://${location.host}/ws/transcribe`);
    this.ws.binaryType = "arraybuffer";
    this.ws.onopen = () => {
      this.ws.send(JSON.stringify({ type: "start", language, title }));
      this.started = true;
      for (const chunk of this.pending) this.ws.send(chunk);
      this.pending = [];
    };
    this.ws.onmessage = (event) => this.onMessage(JSON.parse(event.data));
    this.ws.onerror = () => this.emit("error", { message: "Connection to the server failed." });
    this.ws.onclose = () => this.cleanup();
  }

  onMessage(msg) {
    switch (msg.type) {
      case "ready":
        this.setState("recording");
        this.emit("ready", { provider: msg.provider, model: msg.model, maxSeconds: msg.max_seconds });
        break;
      case "interim":
      case "final":
        this.emit(msg.type, msg);
        break;
      case "saved":
        this.finished = true;
        this.emit("saved", { transcription: msg.transcription });
        break;
      case "empty":
        this.finished = true;
        this.emit("empty");
        break;
      case "info":
        this.emit("info", { message: msg.message });
        if (/maximum/i.test(msg.message)) this.stop();
        break;
      case "error":
        this.emit("error", { message: msg.message });
        break;
    }
  }

  stop() {
    if (this.state !== "recording" && this.state !== "connecting") return;
    this.setState("finishing");
    this.releaseMic();
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "stop" }));
    } else if (this.ws) {
      this.ws.close();
    }
  }

  releaseMic() {
    if (this.node) this.node.port.onmessage = null;
    if (this.stream) this.stream.getTracks().forEach((t) => t.stop());
    if (this.ctx && this.ctx.state !== "closed") this.ctx.close();
    this.stream = this.ctx = this.node = null;
    this.analyser = null;
  }

  cleanup() {
    this.releaseMic();
    this.ws = null;
    this.started = false;
    if (this.state !== "idle") this.setState("idle");
  }
}
