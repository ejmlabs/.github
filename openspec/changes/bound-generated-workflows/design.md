## Design

The generator compresses its own trusted source with the Python standard library and encodes it as base64. When a step would exceed the project run budget, the generator places bounded chunks in that step's static environment and embeds a SHA-256 digest in the short command. The command checks the digest before decoding and running the source. Expressions in source remain encoded, and no product checkout supplies executable source.

The generator validates all generated workflow bytes and run lengths before writing files. It emits UTF-8 LF bytes, and Git attributes preserve LF on checkout. Failure to meet a budget stops generation.

## Verification

Execute generated commands with isolated fixtures, check literal expressions and arguments, reject tampered and missing chunks, compare generated source against reviewed scripts, and test the exact budget boundary. Check LF checkout with Git autocrlf. Run the full repository gate and generated-workflow check. Hosted Linux, macOS and Windows must be verified during pin rollout; local Linux tests do not establish hosted behavior.
