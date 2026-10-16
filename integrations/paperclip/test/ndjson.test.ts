import { describe, expect, test } from "vitest";

import {
  MAX_FRAME_BYTES,
  NdjsonFrameDecoder,
  WIRE_SCHEMA,
  type PaperclipWireEvent,
} from "../src/server/ndjson.js";

/** Build one wire frame exactly as the Python shim writes it. */
function frame(seq: number, event: string, extra: Record<string, unknown> = {}): string {
  return `${JSON.stringify({
    schema: WIRE_SCHEMA,
    seq,
    event,
    run_id: "run_abc123",
    payload: {},
    ...extra,
  })}\n`;
}

function collect(chunks: string[]): PaperclipWireEvent[] {
  const decoder = new NdjsonFrameDecoder();
  const events: PaperclipWireEvent[] = [];
  for (const chunk of chunks) {
    events.push(...decoder.push(chunk));
  }
  decoder.finish();
  return events;
}

describe("NdjsonFrameDecoder", () => {
  test("test_decoder_accepts_multiple_frames", () => {
    const events = collect([
      frame(1, "longrun.run.started") +
        frame(2, "longrun.run.progress", { payload: { iteration: 1, total: 6 } }) +
        frame(3, "longrun.run.completed", { payload: { termination: "completed" } }),
    ]);

    expect(events.map((event) => event.seq)).toEqual([1, 2, 3]);
    expect(events.map((event) => event.event)).toEqual([
      "longrun.run.started",
      "longrun.run.progress",
      "longrun.run.completed",
    ]);
    expect(events[1].payload).toEqual({ iteration: 1, total: 6 });
    expect(events[0].run_id).toBe("run_abc123");
  });

  test("test_decoder_accepts_a_non_consecutive_but_increasing_sequence", () => {
    // The contract is "strictly increasing", not "consecutive": a producer may
    // skip numbers without breaking the reader.
    const events = collect([frame(4, "longrun.run.started"), frame(9, "longrun.run.completed")]);
    expect(events.map((event) => event.seq)).toEqual([4, 9]);
  });

  test("test_decoder_buffers_split_frame", () => {
    const decoder = new NdjsonFrameDecoder();
    const whole = frame(1, "longrun.run.progress", { payload: { iteration: 2, total: 6 } });
    const cut = Math.floor(whole.length / 2);

    expect(decoder.push(whole.slice(0, cut))).toEqual([]);
    expect(decoder.push(whole.slice(cut, whole.length - 1))).toEqual([]);
    const events = decoder.push(whole.slice(whole.length - 1));
    decoder.finish();

    expect(events).toHaveLength(1);
    expect(events[0].payload).toEqual({ iteration: 2, total: 6 });

    // A chunk carrying a whole frame plus the head of the next one returns only
    // the complete frame and keeps the tail buffered.
    const next = new NdjsonFrameDecoder();
    const tail = frame(3, "longrun.run.completed");
    expect(next.push(whole + tail.slice(0, 10))).toHaveLength(1);
    expect(next.push(tail.slice(10))).toHaveLength(1);
    next.finish();
  });

  test("test_decoder_enforces_utf8_frame_limit", () => {
    // A four-byte character keeps the JavaScript length well under the limit
    // while the UTF-8 byte length goes over it: bytes are what counts.
    const heavy = "𝄞".repeat(20_000);
    const line = frame(1, "longrun.run.completed", { payload: { summary: heavy } });
    expect(line.length).toBeLessThan(MAX_FRAME_BYTES);
    expect(Buffer.byteLength(line, "utf8")).toBeGreaterThan(MAX_FRAME_BYTES);

    const decoder = new NdjsonFrameDecoder();
    let failure: unknown = null;
    try {
      decoder.push(line);
      decoder.finish();
    } catch (err) {
      failure = err;
    }
    expect(failure).toBeInstanceOf(Error);
    // The rejected frame is never echoed back into the message.
    expect((failure as Error).message.length).toBeLessThan(300);
    expect((failure as Error).message).not.toContain("𝄞");

    // A frame that fits is accepted.
    const ok = new NdjsonFrameDecoder();
    expect(ok.push(frame(1, "longrun.run.started"))).toHaveLength(1);
    ok.finish();
  });

  test("test_decoder_rejects_bad_schema_and_sequence", () => {
    const rejects = (line: string) => {
      const decoder = new NdjsonFrameDecoder();
      expect(() => decoder.push(line)).toThrow();
    };

    // Unknown schema version.
    rejects(frame(1, "longrun.run.started", { schema: "longrun.paperclip.event.v2" }));
    // Unknown event type.
    rejects(frame(1, "agent.think"));
    rejects(frame(1, "longrun.run.unknown"));
    // Malformed JSON.
    rejects("{not json}\n");
    // Payload must be an object, not a string, array, or null.
    rejects(frame(1, "longrun.run.started", { payload: "text" }));
    rejects(frame(1, "longrun.run.started", { payload: [] }));
    // run_id must be a non-empty string when present.
    rejects(frame(1, "longrun.run.started", { run_id: 7 }));
    rejects(frame(1, "longrun.run.started", { run_id: "" }));
    // Sequence must be a positive integer, strictly increasing.
    rejects(frame(0, "longrun.run.started"));
    rejects(frame(-1, "longrun.run.started"));
    rejects(frame(1.5, "longrun.run.started"));

    const regression = new NdjsonFrameDecoder();
    regression.push(frame(2, "longrun.run.started"));
    expect(() => regression.push(frame(1, "longrun.run.progress"))).toThrow();
    // A duplicate is not an increase either.
    expect(() => regression.push(frame(2, "longrun.run.progress"))).toThrow();

    // After a rejection the decoder stays failed and holds no buffered data.
    expect(() => regression.push(frame(3, "longrun.run.completed"))).toThrow();
    expect(() => regression.finish()).toThrow();
  });

  test("test_decoder_requires_terminal_frame", () => {
    // An unterminated final frame is a protocol error, never a silent drop.
    const decoder = new NdjsonFrameDecoder();
    decoder.push(frame(1, "longrun.run.started"));
    decoder.push('{"schema":"longrun.paperclip.event.v1","seq":2');
    expect(() => decoder.finish()).toThrow();

    // A trailing newline leaves nothing pending.
    const clean = new NdjsonFrameDecoder();
    clean.push(frame(1, "longrun.run.started"));
    expect(() => clean.finish()).not.toThrow();

    // Trailing whitespace-only content is not a frame.
    const padded = new NdjsonFrameDecoder();
    padded.push(frame(1, "longrun.run.started") + "\n  \n");
    expect(() => padded.finish()).not.toThrow();
  });
});
