import ast, os, sys

root = "src"
errors = []
for dp, dn, fn in os.walk(root):
    for f in fn:
        if f.endswith(".py"):
            fpath = os.path.join(dp, f)
            try:
                with open(fpath, "r", encoding="utf-8") as fh:
                    ast.parse(fh.read(), filename=fpath)
                print(f"  OK: {fpath}")
            except SyntaxError as e:
                errors.append(f"{fpath}: {e}")
                print(f"  ERR: {fpath}: {e}")

if errors:
    print(f"\n{len(errors)} syntax error(s) found!")
    sys.exit(1)
else:
    print("\nAll files parse OK.")
