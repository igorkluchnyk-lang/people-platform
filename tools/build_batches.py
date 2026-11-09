"""Перетворює папку seed/<колекція>/<id>.json на батчі для ArtifactData (до 50 записів у батчі).

Використання:
  python3 tools/build_batches.py seed_example out/
Далі кожен out/batch_N.json передається в ArtifactData action "batch" як writes.
Нові документи пишуться через "set" без if_version. Для оновлення наявних
спершу прочитай документ і додай if_version руками (або перезапиши через set з if_version).
"""
import json, os, sys, glob

src, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
writes = []
for f in sorted(glob.glob(os.path.join(src, "**", "*.json"), recursive=True)):
    rel = os.path.relpath(f, src)
    col, doc = os.path.dirname(rel), os.path.basename(rel)[:-5]
    if not col:
        continue
    writes.append({"op": "set", "collection": col.replace(os.sep, "/"), "doc_id": doc,
                   "file_path": os.path.abspath(f)})
for i in range(0, len(writes), 50):
    p = os.path.join(out, f"batch_{i // 50 + 1}.json")
    json.dump(writes[i:i + 50], open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(p, len(writes[i:i + 50]))
