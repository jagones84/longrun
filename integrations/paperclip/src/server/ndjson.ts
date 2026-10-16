/**
 * Bounded, incremental reader for the Longrun child's NDJSON protocol.
 *
 * The child (`forge.py paperclip-bot`) writes exactly one JSON object per line
 * on stdout and nothing else. This decoder turns arbitrary stdout chunks into
 * validated protocol frames, or fails the run.
 *
 * Failure is always closed and always quiet: a rejected frame is never echoed
 * back into the error message, because a raw protocol line may carry task text
 * or a credential, and Paperclip logs are user-visible.
 */

/** Wire schema understood by this decoder. */
export const WIRE_SCHEMA = "longrun.paperclip.event.v1";

/** Largest accepted frame, measured in UTF-8 bytes. */
export const MAX_FRAME_BYTES = 65_536;

/** The complete allowlist of forwarded event types. */
export const WIRE_EVENTS = [
  "longrun.run.started",
  "longrun.run.progress",
  "longrun.run.completed",
  "longrun.run.failed",
  "longrun.run.cancelled",
] as const;

export type PaperclipEventName = (typeof WIRE_EVENTS)[number];

/** One validated protocol frame. */
export interface PaperclipWireEvent {
  schema: typeof WIRE_SCHEMA;
  seq: number;
  event: PaperclipEventName;
  run_id: string | null;
  payload: Record<string, unknown>;
}

const KNOWN_EVENTS = new Set<string>(WIRE_EVENTS);

/** Protocol violation. The message never contains frame content. */
export class ProtocolError extends Error {}

function utf8Length(text: string): number {
  return Buffer.byteLength(text, "utf8");
}

/**
 * Incremental NDJSON frame decoder.
 *
 * `push` accepts a chunk of any size, including chunks that split a frame, and
 * returns the frames it completed. A blank or whitespace-only line is ignored;
 * everything else must be one valid frame.
 *
 * Once a frame is rejected the decoder is poisoned: it holds no buffered data
 * and every later `push` or `finish` throws, so a corrupt stream cannot be
 * half-read into a success.
 */
export class NdjsonFrameDecoder {
  #buffer = "";
  #lastSeq = 0;
  #failed: Error | null = null;

  /** Feed one stdout chunk; return the frames completed by it. */
  push(chunk: string): PaperclipWireEvent[] {
    this.#assertHealthy();
    this.#buffer += chunk;
    const events: PaperclipWireEvent[] = [];
    let newline = this.#buffer.indexOf("\n");
    while (newline >= 0) {
      const line = this.#buffer.slice(0, newline);
      this.#buffer = this.#buffer.slice(newline + 1);
      const parsed = this.#parse(line);
      if (parsed) events.push(parsed);
      newline = this.#buffer.indexOf("\n");
    }
    return events;
  }

  /**
   * Assert the stream ended on a frame boundary.
   *
   * A non-empty remainder means the child stopped mid-frame: a truncated
   * protocol, never a silent drop.
   */
  finish(): void {
    this.#assertHealthy();
    if (this.#buffer.trim().length > 0) {
      this.#buffer = "";
      this.#fail("the protocol stream ended inside an unterminated frame");
    }
  }

  #parse(line: string): PaperclipWireEvent | null {
    if (line.trim().length === 0) return null;
    try {
      return this.#validate(line);
    } catch (err) {
      // Drop what was buffered with the rejected frame: the stream is no
      // longer trustworthy.
      this.#buffer = "";
      this.#fail(err instanceof Error ? err.message : "invalid protocol frame");
      return null;
    }
  }

  #validate(line: string): PaperclipWireEvent {
    if (utf8Length(line) > MAX_FRAME_BYTES) {
      throw new ProtocolError(`a protocol frame exceeded ${MAX_FRAME_BYTES} bytes`);
    }

    let decoded: unknown;
    try {
      decoded = JSON.parse(line);
    } catch {
      throw new ProtocolError("a protocol frame was not valid JSON");
    }
    if (typeof decoded !== "object" || decoded === null || Array.isArray(decoded)) {
      throw new ProtocolError("a protocol frame was not a JSON object");
    }

    const record = decoded as Record<string, unknown>;
    if (record.schema !== WIRE_SCHEMA) {
      throw new ProtocolError("a protocol frame declared an unsupported schema");
    }
    if (typeof record.event !== "string" || !KNOWN_EVENTS.has(record.event)) {
      throw new ProtocolError("a protocol frame declared an unsupported event type");
    }

    const seq = record.seq;
    if (typeof seq !== "number" || !Number.isInteger(seq) || seq < 1) {
      throw new ProtocolError("a protocol frame carried a non-positive sequence number");
    }
    if (seq <= this.#lastSeq) {
      throw new ProtocolError(
        `protocol sequence numbers must increase: expected above ${this.#lastSeq}, received ${seq}`,
      );
    }

    const runId = record.run_id ?? null;
    if (runId !== null && (typeof runId !== "string" || runId.length === 0)) {
      throw new ProtocolError("a protocol frame carried an invalid run id");
    }

    const payload = record.payload ?? {};
    if (typeof payload !== "object" || payload === null || Array.isArray(payload)) {
      throw new ProtocolError("a protocol frame carried an invalid payload");
    }

    this.#lastSeq = seq;
    return {
      schema: WIRE_SCHEMA,
      seq,
      event: record.event as PaperclipEventName,
      run_id: runId,
      payload: payload as Record<string, unknown>,
    };
  }

  #assertHealthy(): void {
    if (this.#failed) throw this.#failed;
  }

  #fail(message: string): never {
    const error = new ProtocolError(message);
    this.#failed = error;
    throw error;
  }
}
