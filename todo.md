# TODO

## Stdin Recorder

Add a helper tool that records manual stdin for later deterministic runs.

Possible CLI shape:

```text
calcchain record-stdin --output stdin.txt -- python script.py
```

The tool should:

- run the target command interactively;
- forward process stdout/stderr to the terminal;
- read user input from stdin;
- write the same input to the child process stdin;
- record that input to a file;
- let later runs reuse the recording with `stdin_mode = "script"`.

For simple line-oriented CLIs this can be implemented with `subprocess` pipes and threads for stdout/stderr forwarding. True terminal interaction, raw mode, TUI programs, and password prompts without echo would require a PTY/ConPTY based runner, so that should be treated as a separate feature.
