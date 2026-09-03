# ASR v1 contract

`asr-v1.schema.json` is the shared JSON message contract for the Windows client and the future ASR service. `asr-v1.examples.json` contains canonical client and server messages used by contract tests.

The Schema is strict. Message types reject unknown fields, every event has a non-empty `session_id`, and `transcript.final.seq` is a positive integer that increases within a session. A protocol change is incomplete until the Schema, examples, Python models, parser and tests agree.

After `stream.start` and `stream.ready`, audio messages are binary. Each message contains exactly 3200 bytes of 16 kHz mono PCM16 little-endian audio, representing 100 ms. Binary audio is not represented by the JSON Schema.

There is no partial transcript event. The client sends `stream.stop`, keeps receiving final events, and closes only after `stream.stopped` or an explicit timeout. Lifecycle acknowledgements must not wait behind a full subtitle event queue.
