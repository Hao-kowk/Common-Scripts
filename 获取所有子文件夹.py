import os
import sys

INPUT_FILE = '文件夹列表.txt'
OUTPUT_FILE = 'filtered_dirs.txt'

# ---------- 自动探测编码 ----------
encodings = ['gbk', 'utf-8-sig', 'utf-16', 'utf-8']
content_lines = None
for enc in encodings:
    try:
        with open(INPUT_FILE, 'r', encoding=enc) as f:
            content_lines = f.readlines()
        print(f"✅ 成功使用编码 [{enc}] 读取文件。")
        break
    except UnicodeDecodeError:
        continue

if content_lines is None:
    print("❌ 无法解码文件，请确认文件是否损坏。")
    input("按 Enter 退出...")
    sys.exit(1)

lines = [line.strip() for line in content_lines if line.strip()]
print(f"✅ 共读取 {len(lines)} 行。正在筛选...")

# ---------- 修正后的匹配规则（注意末尾没有反斜杠） ----------
roots = (r'F:\Browser', r'F:\Internet', r'F:\Message', r'F:\Security', r'F:\Tools')

target_paths = []
for p in lines:
    p_clean = p.replace('/', '\\')
    for root in roots:
        if p_clean.startswith(root):
            target_paths.append(p_clean)
            break

print(f"✅ 属于 5 个根目录的路径有 {len(target_paths)} 条。")

# ---------- 保留有子文件夹的目录（排除叶子） ----------
path_set = set(target_paths)
result = []
for p in target_paths:
    # 检查是否存在比 p 更深一层的路径（即子文件夹）
    if any(q.startswith(p + '\\') for q in path_set):
        result.append(p)

# 可选：排除根目录本身（如果你需要根目录，可以删除下面两行）
result = [p for p in result if p not in roots]

print(f"🎉 完成！共保留 {len(result)} 个非叶子文件夹路径（已排除根目录）。")
print(f"📁 结果已保存至：{OUTPUT_FILE}")

with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
    f.write('\n'.join(result))

input("按 Enter 退出...")