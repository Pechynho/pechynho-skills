# Several records in one call

Every call of a tool ([plan](plan-tool.md), [review](review-tool.md), [browser](browser-tool.md)) is one
tool call of the agent. Record what a returned run produced in as few calls as possible: one command
with several IDs when the items share their arguments, one `batch` when they differ.

## Several IDs

The commands that change one item by ID take several when the rest of the arguments is the same for all
of them, for example `review.py … verify R3-01 R3-02 confirmed --verifier V2` or
`plan.py … set T-003 T-004 done --evidence "…"`. Each tool names its commands that do.

## Batch

`batch FILE` reads the commands from a file, `batch -` from the standard input. Each line is one command
without the folder path, in one of two forms:

- the arguments as on the command line, split by shell quoting rules without any expansion;
- a JSON array of the arguments, for values with quotes or line breaks.

Empty lines and lines starting with `#` are skipped. A heredoc with a quoted delimiter passes the lines
to `-` unchanged:

```bash
python3 <skill directory>/shared/plan.py {plans_dir}/{feature} batch - <<'EOF'
set T-003 T-004 done --evidence "done_when met; make test passes"
log check subject="make test" result=pass tasks='["T-003", "T-004"]'
["log", "note", "text=The \"legacy\" export stays until T-007"]
EOF
```

Each tool lists the commands a batch accepts; commands that only read, create the folder or run
something are not among them.

## All or nothing

A command with several IDs and a batch change the state together or not at all. The commands run in
order and each sees the effect of the previous ones; the first refusal or wrong usage stops them, the
tool writes nothing and names the failing line or ID. Fix it and send the whole call again. The log
keeps one record per item, as if the commands had run one by one.
