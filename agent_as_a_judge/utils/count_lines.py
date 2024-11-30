def count_lines_of_code(filepaths):

    total_lines = 0
    total_files = 0
    for filepath in filepaths:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()
            total_lines += len(lines)
            total_files += 1
    return total_lines, total_files
