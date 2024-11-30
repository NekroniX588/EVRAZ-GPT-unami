import os
import re
import ast
import json
import pickle

import inspect
import builtins
import networkx as nx

from copy import deepcopy
from collections import namedtuple
from pathlib import Path
from dotenv import load_dotenv
from matplotlib import pyplot as plt
from tqdm import tqdm
from typing import List

from pygments.lexers import guess_lexer_for_filename
from pygments.token import Token
from pygments.util import ClassNotFound
from tree_sitter_languages import get_language, get_parser
from grep_ast import TreeContext, filename_to_lang
from concurrent.futures import ThreadPoolExecutor, as_completed

Tag = namedtuple("Tag", "rel_fname fname line name identifier category details".split())


class DevGraph:

    def __init__(
        self,
        root=None,
        io=None,
        verbose=False,
        include_dirs=None,
        exclude_dirs=None,
        exclude_files=None,
    ):
        self.io = io
        self.verbose = verbose
        self.root = root or os.getcwd()
        self.include_dirs = include_dirs
        self.exclude_dirs = exclude_dirs or ["__pycache__", "env", "venv"]
        self.exclude_files = exclude_files or [".DS_Store"]
        self.structure = self.create_structure(self.root)
        self.warned_files = set()
        self.tree_cache = {}

    def build(self, filepaths, mentioned=None):
        if not filepaths:
            return None, None

        mentioned = mentioned or set()
        tags = self._get_tags_from_files(filepaths, mentioned)
        dev_graph = self._tags_to_graph(tags)

        return tags, dev_graph

    def _get_tags_from_files(self, filepaths, mentioned=None):
        try:
            tags_of_files = []
            filepaths = sorted(set(filepaths))

            with ThreadPoolExecutor() as executor:
                future_to_filepath = {
                    executor.submit(self._process_file, filepath): filepath
                    for filepath in filepaths
                }

                for future in as_completed(future_to_filepath):
                    tags = future.result()
                    if tags:
                        tags_of_files.extend(tags)

            return tags_of_files

        except RecursionError:
            self.io.tool_error("Disabling code graph, git repo too large?")
            return None

    def _process_file(self, filepath):
        if not self._is_valid_file(filepath):
            return []

        relative_filepath = self.get_relative_filepath(filepath)
        tags = list(self.get_tags(filepath, relative_filepath))
        return tags

    def _is_valid_file(self, filepath):
        if not Path(filepath).is_file():
            if filepath not in self.warned_files:
                self._log_file_warning(filepath)
            return False
        return True

    def _log_file_warning(self, filepath):
        if Path(filepath).exists():
            self.io.tool_error(
                f"Code graph can't include {filepath}, it is not a normal file"
            )
        else:
            self.io.tool_error(
                f"Code graph can't include {filepath}, it no longer exists"
            )
        self.warned_files.add(filepath)

    def get_relative_filepath(self, filepath):
        return os.path.relpath(filepath, self.root)

    def get_tags(self, filepath, relative_filepath):
        file_mtime = self._get_modified_time(filepath)
        if file_mtime is None:
            return []

        return list(self._get_tags_raw(filepath, relative_filepath))

    def _get_modified_time(self, fname):
        try:
            return os.path.getmtime(fname)
        except FileNotFoundError:
            self.io.tool_error(f"File not found error: {fname}")

    def _get_tags_raw(self, filepath, relative_filepath):

        relative_filepath_list = relative_filepath.split("/")
        s = self._navigate_structure(relative_filepath_list)
        if s is None:
            return

        structure_classes, structure_all_funcs = self._extract_structure_info(s)

        lang, parser = self._get_language_parser(filepath)
        if not lang:
            return

        code, codelines = self._read_code(filepath)
        if not code:
            return

        tree = parser.parse(bytes(code, "utf-8"))

        try:
            std_funcs, std_libs = self._std_proj_funcs(code, filepath)
        except Exception:
            std_funcs, std_libs = [], []

        builtins_funs = [name for name in dir(builtins)]
        builtins_funs += dir(list)
        builtins_funs += dir(dict)
        builtins_funs += dir(set)
        builtins_funs += dir(str)
        builtins_funs += dir(tuple)

        captures = self._get_syntax_captures(lang, tree)

        # Process each capture, identifying and categorizing them
        saw = set()  # Set to record encountered tag types

        def_count = 0
        ref_count = 0

        for node, tag in captures:
            if tag.startswith("name.definition."):
                identifier = "def"  # Define a class or function
                def_count += 1
            elif tag.startswith("name.reference."):
                identifier = "ref"  # Reference a class or function
                ref_count += 1
            else:
                continue

            saw.add(identifier)  # Record the encountered tag type

            cur_cdl = codelines[node.start_point[0]]  # Get the current code line
            category = "class" if "class " in cur_cdl else "function"
            tag_name = node.text.decode("utf-8")  # Get the tag name

            # Ignore standard functions, standard libraries, and built-in functions
            if (
                tag_name in std_funcs
                or tag_name in std_libs
                or tag_name in builtins_funs
            ):
                continue

            # Initialize the result to None
            result = None

            if category == "class":
                if tag_name in structure_classes:
                    if "methods" in structure_classes[tag_name]:
                        class_functions = [
                            item["name"]
                            for item in structure_classes[tag_name]["methods"]
                        ]
                    else:
                        class_functions = []

                    if identifier == "def":
                        line_nums = [
                            structure_classes[tag_name]["start_line"],
                            structure_classes[tag_name]["end_line"],
                        ]
                    else:
                        line_nums = [node.start_point[0], node.end_point[0]]

                    result = Tag(
                        rel_fname=relative_filepath,
                        fname=filepath,
                        name=tag_name,
                        identifier=identifier,
                        category=category,
                        details="\n".join(class_functions),  # Class method information
                        line=line_nums,
                    )
                else:
                    print(f"Warning: Class {tag_name} not found in structure")
            elif category == "function":
                if identifier == "def":
                    cur_cdl = "\n".join(
                        structure_all_funcs.get(tag_name, {}).get("text", [])
                    )
                    line_nums = [
                        structure_all_funcs.get(tag_name, {}).get(
                            "start_line", node.start_point[0]
                        ),
                        structure_all_funcs.get(tag_name, {}).get(
                            "end_line", node.end_point[0]
                        ),
                    ]
                else:
                    line_nums = [node.start_point[0], node.end_point[0]]

                result = Tag(
                    rel_fname=relative_filepath,
                    fname=filepath,
                    name=tag_name,
                    identifier=identifier,
                    category=category,
                    details=cur_cdl,
                    line=line_nums,
                )

            if result:  # Check if the result is not None
                yield result

        if "ref" in saw or "def" not in saw:
            return  # Return if any references are found or if no definitions are found

        yield from self._process_additional_tokens(
            filepath, relative_filepath, codelines
        )

    def _navigate_structure(self, relative_filepath_list):
        s = deepcopy(self.structure)
        for fname_part in relative_filepath_list:
            s = s.get(fname_part)
            if s is None:
                return None
        return s

    def _extract_structure_info(self, s):
        structure_classes = {item["name"]: item for item in s.get("classes", [])}
        structure_functions = {item["name"]: item for item in s.get("functions", [])}
        structure_class_methods = {
            item["name"]: item
            for cls in s.get("classes", [])
            for item in cls.get("methods", [])
        }
        structure_all_funcs = {**structure_functions, **structure_class_methods}

        return structure_classes, structure_all_funcs

    def _get_language_parser(self, filepath):
        lang = filename_to_lang(filepath)
        if not lang:
            return None, None
        language = get_language(lang)
        parser = get_parser(lang)
        return language, parser

    def _read_code(self, filepath):

        with open(filepath, "r", encoding="utf-8") as f:
            code = f.read()

        # Preprocess the code content, replacing some special characters and patterns
        code = code.replace("\ufeff", "")  # Remove BOM marker
        code = code.replace("constants.False", "_False")
        code = code.replace("constants.True", "_True")
        code = code.replace("False", "_False")
        code = code.replace("True", "_True")
        code = code.replace("DOMAIN\\username", "DOMAIN\\\\username")
        code = code.replace("Error, ", "Error as ")
        code = code.replace("Exception, ", "Exception as ")
        code = code.replace("print ", "yield ")

        # Replace some exception handling patterns to match new syntax
        pattern = r"except\s+\(([^,]+)\s+as\s+([^)]+)\):"
        code = re.sub(pattern, r"except (\1, \2):", code)
        code = code.replace("raise AttributeError as aname", "raise AttributeError")

        if not code:
            return "", []

        with open(str(filepath), "r", encoding="utf-8") as f:
            codelines = f.readlines()

        return code, codelines

    def _get_syntax_captures(self, language, tree):
        query_scm = """
        (class_definition
        name: (identifier) @name.definition.class) @definition.class

        (function_definition
        name: (identifier) @name.definition.function) @definition.function

        (call
        function: [
            (identifier) @name.reference.call
            (attribute
                attribute: (identifier) @name.reference.call)
        ]) @reference.call
        """
        query = language.query(query_scm)
        return query.captures(tree.root_node)

    def _process_captures(
        self,
        captures,
        codelines,
        std_funcs,
        std_libs,
        builtins_funs,
        structure_classes,
        structure_all_funcs,
        filepath,
        relative_filepath,
    ):

        captures = list(captures)
        saw = set()

        def_count = 0
        ref_count = 0

        for node, tag in captures:
            if tag.startswith("name.definition."):
                identifier = "def"  # Define a class or function
                def_count += 1
            elif tag.startswith("name.reference."):
                identifier = "ref"  # Reference a class or function
                ref_count += 1
            else:
                continue

            saw.add(identifier)

            cur_cdl = codelines[node.start_point[0]]  # Get the current code line
            category = (
                "class" if "class " in cur_cdl else "function"
            )  # Determine if the tag belongs to a class or function
            tag_name = node.text.decode("utf-8")  # Get the tag name

            if tag_name in std_funcs:
                continue
            elif tag_name in std_libs:
                continue
            elif tag_name in builtins_funs:
                continue

            if category == "class":
                # Handle class tag information
                class_functions = [
                    item["name"] for item in structure_classes[tag_name]["methods"]
                ]
                if identifier == "def":
                    line_nums = [
                        structure_classes[tag_name]["start_line"],
                        structure_classes[tag_name]["end_line"],
                    ]
                else:
                    line_nums = [node.start_point[0], node.end_point[0]]
                result = Tag(
                    rel_fname=relative_filepath,
                    fname=filepath,
                    name=tag_name,
                    identifier=identifier,
                    category=category,
                    details="\n".join(class_functions),  # Class method information
                    line=line_nums,
                )
            elif category == "function":
                # Handle function tag information
                if identifier == "def":
                    cur_cdl = "\n".join(structure_all_funcs[tag_name]["text"])
                    line_nums = [
                        structure_all_funcs[tag_name]["start_line"],
                        structure_all_funcs[tag_name]["end_line"],
                    ]
                else:
                    line_nums = [node.start_point[0], node.end_point[0]]

                result = Tag(
                    rel_fname=relative_filepath,
                    fname=filepath,
                    name=tag_name,
                    identifier=identifier,
                    category=category,
                    details=cur_cdl,
                    line=line_nums,
                )

            yield result  # Generate tag result

        if "ref" in saw or "def" not in saw:
            return

        yield from self._process_additional_tokens(
            filepath, relative_filepath, codelines
        )

    def _identify_tag(self, node, tag, codelines):
        if tag.startswith("name.definition."):
            identifier = "def"
        elif tag.startswith("name.reference."):
            identifier = "ref"
        else:
            return None, None

        cur_cdl = codelines[node.start_point[0]]
        category = "class" if "class " in cur_cdl else "function"
        return identifier, category

    def _is_ignored_tag(self, tag_name, std_funcs, std_libs):
        return (
            tag_name in std_funcs or tag_name in std_libs or tag_name in dir(builtins)
        )

    def _create_class_tag(
        self, tag_name, identifier, structure_classes, node, filepath, relative_filepath
    ):
        class_info = structure_classes.get(tag_name, {})
        class_methods = "\n".join(
            [item["name"] for item in class_info.get("methods", [])]
        )
        line_nums = [
            class_info.get("start_line", node.start_point[0]),
            class_info.get("end_line", node.end_point[0]),
        ]
        return Tag(
            rel_fname=relative_filepath,
            fname=filepath,
            name=tag_name,
            identifier=identifier,
            category="class",
            details=class_methods,
            line=line_nums,
        )

    def _create_function_tag(
        self,
        tag_name,
        identifier,
        structure_all_funcs,
        node,
        filepath,
        relative_filepath,
        codelines,
    ):
        func_info = structure_all_funcs.get(tag_name, {})
        line_nums = [
            func_info.get("start_line", node.start_point[0]),
            func_info.get("end_line", node.end_point[0]),
        ]
        details = "\n".join(
            func_info.get("text", codelines[node.start_point[0] : node.end_point[0]])
        )
        return Tag(
            rel_fname=relative_filepath,
            fname=filepath,
            name=tag_name,
            identifier=identifier,
            category="function",
            details=details,
            line=line_nums,
        )

    def _process_additional_tokens(self, filepath, relative_filepath, codelines):

        code = "\n".join(codelines)

        try:
            lexer = guess_lexer_for_filename(filepath, code)
        except ClassNotFound:
            return

        tokens = list(lexer.get_tokens(code))
        tokens = [token[1] for token in tokens if token[0] in Token.Name]

        for token in tokens:
            yield Tag(
                rel_fname=relative_filepath,
                fname=filepath,
                name=token,
                identifier="ref",
                line=-1,
                category="function",
                details="none",
            )

    def _tags_to_graph(self, tags):
        G = nx.MultiDiGraph()

        for tag in tags:
            G.add_node(
                tag.name,
                category=tag.category,
                details=tag.details,
                fname=tag.fname,
                line=tag.line,
                identifier=tag.identifier,
            )

        for tag in tags:
            if tag.category == "class":
                self._add_class_edges(G, tag)

        self._add_reference_edges(G, tags)
        return G

    def _add_class_edges(self, G, tag):
        class_funcs = tag.details.split("\n")
        for f in class_funcs:
            G.add_edge(tag.name, f.strip())

    def _add_reference_edges(self, G, tags):
        tags_ref = [tag for tag in tags if tag.identifier == "ref"]
        tags_def = [tag for tag in tags if tag.identifier == "def"]
        for tag_ref in tags_ref:
            for tag_def in tags_def:
                if tag_ref.name == tag_def.name:
                    G.add_edge(tag_ref.name, tag_def.name)

    def split_path(self, path):
        path = os.path.relpath(path, self.root)
        return [path + ":"]

    def get_class_functions(self, tree, class_name):
        class_functions = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        class_functions.append(item.name)

        return class_functions

    def get_func_block(self, first_line, code_block):
        first_line_escaped = re.escape(first_line)
        pattern = re.compile(
            rf"({first_line_escaped}.*?)(?=(^\S|\Z))", re.DOTALL | re.MULTILINE
        )
        match = pattern.search(code_block)

        return match.group(0) if match else None

    def _std_proj_funcs(self, code, fname):
        std_libs = []
        std_funcs = []
        tree = ast.parse(code)
        codelines = code.split("\n")

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                import_statement = codelines[node.lineno - 1]
                for alias in node.names:
                    import_name = alias.name.split(".")[0]
                    if import_name in fname:
                        continue
                    else:
                        try:
                            exec(import_statement.strip())
                        except:
                            continue
                        std_libs.append(alias.name)
                        eval_name = alias.name if alias.asname is None else alias.asname
                        std_funcs.extend(
                            [
                                name
                                for name, member in inspect.getmembers(eval(eval_name))
                                if callable(member)
                            ]
                        )

            if isinstance(node, ast.ImportFrom):
                import_statement = codelines[node.lineno - 1]
                if node.module is None:
                    continue
                module_name = node.module.split(".")[0]
                if module_name in fname:
                    continue
                else:
                    if "(" in import_statement:
                        for ln in range(node.lineno - 1, len(codelines)):
                            if ")" in codelines[ln]:
                                code_num = ln
                                break
                        import_statement = "\n".join(
                            codelines[node.lineno - 1 : code_num + 1]
                        )
                    try:
                        exec(import_statement.strip())
                    except:
                        continue
                    for alias in node.names:
                        std_libs.append(alias.name)
                        eval_name = alias.name if alias.asname is None else alias.asname
                        if eval_name == "*":
                            continue
                        std_funcs.extend(
                            [
                                name
                                for name, member in inspect.getmembers(eval(eval_name))
                                if callable(member)
                            ]
                        )
        return std_funcs, std_libs

    def create_structure(self, directory_path):
        structure = {}
        main_file_set = set(self.list_all_files(directory_path))
        num_files = len(list(os.walk(directory_path)))
        for root, _, files in tqdm(
            os.walk(directory_path), total=num_files, desc="Parsing files"
        ):
            relative_root = os.path.relpath(root, directory_path)
            current_structure = structure

            if relative_root != ".":
                for part in relative_root.split(os.sep):
                    if part not in current_structure:
                        current_structure[part] = {}
                    current_structure = current_structure[part]

            for filename in files:
                if filename.endswith(".py"):
                    filepath = os.path.join(root, filename)
                    if filepath not in main_file_set:
                        continue  # added to avoid parsing the contents of venv/
                    class_info, function_names, code_lines = self.parse_python_file(
                        filepath
                    )
                    current_structure[filename] = {
                        "classes": class_info,
                        "functions": function_names,
                        "code": code_lines,
                    }
                else:
                    current_structure[filename] = {}

        return structure

    def parse_python_file(self, file_path, file_content=None):
        if file_content is None:
            try:
                with open(file_path, "r") as file:
                    file_content = file.read()
                    parsed_data = ast.parse(file_content)
            except Exception as e:
                print(f"Error in file {file_path}: {e}")
                return [], [], ""
        else:
            try:
                parsed_data = ast.parse(file_content)
            except Exception as e:
                print(f"Error in file {file_path}: {e}")
                return [], [], ""

        class_info = []
        function_names = []
        class_methods = set()

        for node in ast.walk(parsed_data):
            if isinstance(node, ast.ClassDef):
                methods = []
                for n in node.body:
                    if isinstance(n, ast.FunctionDef):
                        methods.append(
                            {
                                "name": n.name,
                                "start_line": n.lineno,
                                "end_line": n.end_lineno,
                                "text": file_content.splitlines()[
                                    n.lineno - 1 : n.end_lineno
                                ],
                            }
                        )
                        class_methods.add(n.name)
                class_info.append(
                    {
                        "name": node.name,
                        "start_line": node.lineno,
                        "end_line": node.end_lineno,
                        "text": file_content.splitlines()[
                            node.lineno - 1 : node.end_lineno
                        ],
                        "methods": methods,
                    }
                )
            elif isinstance(node, ast.FunctionDef) and not isinstance(
                node, ast.AsyncFunctionDef
            ):
                if node.name not in class_methods:
                    function_names.append(
                        {
                            "name": node.name,
                            "start_line": node.lineno,
                            "end_line": node.end_lineno,
                            "text": file_content.splitlines()[
                                node.lineno - 1 : node.end_lineno
                            ],
                        }
                    )

        return class_info, function_names, file_content.splitlines()

    def render_tree(self, abs_fname, rel_fname, lois):
        key = (rel_fname, tuple(sorted(lois)))

        if key in self.tree_cache:
            return self.tree_cache[key]

        with open(str(abs_fname), "r", encoding="utf-8") as f:
            code = f.read() or ""

        if not code.endswith("\n"):
            code += "\n"

        context = TreeContext(
            rel_fname,
            code,
            color=False,
            line_number=False,
            child_context=False,
            last_line=False,
            margin=0,
            mark_lois=False,
            loi_pad=0,
            show_top_of_file_parent_scope=False,
        )

        context.add_lines_of_interest(lois)
        context.add_context()
        res = context.format()
        self.tree_cache[key] = res
        return res

    def to_tree(self, tags, chat_rel_fnames):
        if not tags:
            return ""

        tags = [tag for tag in tags if tag[0] not in chat_rel_fnames]
        tags = sorted(tags)
        cur_fname = None
        cur_abs_fname = None
        lois = None
        output = ""
        dummy_tag = (None,)

        for tag in tags + [dummy_tag]:
            this_rel_fname = tag[0]

            # ... here ... to output the final real entry in the list
            if this_rel_fname != cur_fname:
                if lois is not None:
                    output += "\n"
                    output += cur_fname + ":\n"
                    output += self.render_tree(cur_abs_fname, cur_fname, lois)
                    lois = None
                elif cur_fname:
                    output += "\n" + cur_fname + "\n"
                if identifier(tag) is Tag:
                    lois = []
                    cur_abs_fname = tag.fname
                cur_fname = this_rel_fname

            if lois is not None:
                lois.append(tag.line)

        # truncate long lines, in case we get minified js or something else crazy
        output = "\n".join([line[:100] for line in output.splitlines()]) + "\n"

        return output

    def list_all_files(self, directory):
        """
        Recursively list all files under the given directory while applying the
        inclusion/exclusion rules for directories and files, and excluding hidden files.
        """
        main_files = []
        include_all = self.include_dirs is None

        for root, dirs, files in os.walk(directory):
            dirs[:] = [
                d
                for d in dirs
                if not any(
                    excluded in os.path.basename(d) for excluded in self.exclude_dirs
                )
            ]
            if include_all or any(included in root for included in self.include_dirs):
                for file in files:
                    file_path = os.path.join(root, file)
                    if not file.startswith(".") and not any(
                        excluded_file in file for excluded_file in self.exclude_files
                    ):
                        main_files.append(file_path)

        return main_files

    def list_py_files(self, directories: List, python_only=True):
        files = []
        for directory in directories:
            if Path(directory).is_dir():
                files += self.list_all_files(
                    directory
                )  # Recursively get all files/directories
            else:
                files.append(directory)

        if not python_only:
            return files

        python_files = []
        for item in files:
            if not str(item).endswith(".py"):
                continue

            # relative_path = os.path.relpath(item, self.root)
            # if self._is_included(relative_path):
            #     python_files.append(item)
            python_files.append(item)

        return python_files

    def save_file_structure(self, dir, save_dir):
        """
        Recursively save the directory structure into a JSON file, while applying the
        inclusion/exclusion rules for directories and files, and excluding hidden files.
        """

        def build_tree_structure(current_path):
            tree = {}
            include_all = self.include_dirs is None

            for root, dirs, files in os.walk(current_path):
                dirs[:] = [
                    d
                    for d in dirs
                    if not any(excluded in d for excluded in self.exclude_dirs)
                    and not d.startswith(".")
                ]
                if include_all or any(
                    included in root for included in self.include_dirs
                ):
                    relative_root = os.path.relpath(root, self.root)

                    tree[relative_root] = {}
                    for file in files:
                        file_path = os.path.join(root, file)
                        if not file.startswith(".") and not any(
                            excluded_file in file
                            for excluded_file in self.exclude_files
                        ):
                            # Add the file to the tree structure
                            tree[relative_root][file] = None

            return tree

        # Build the directory tree structure
        tree_structure = build_tree_structure(dir)

        print(
            f"🌲 Successfully constructed the directory tree structure for directory ''{dir}： \n{tree_structure}''"
        )
        project_data = {"workspace": dir, "tree_structure": tree_structure}

        with open(save_dir, "w", encoding="utf-8") as f:
            json.dump(str(project_data), f, indent=4, ensure_ascii=False)

    def count_lines_of_code(self, filepaths):
        """Count the total number of lines of code in the given file paths."""
        total_lines = 0
        total_files = 0

        for filepath in filepaths:
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    total_lines += len(lines)
                    total_files += 1
            except Exception as e:
                self.io.tool_error(f"Error reading file {filepath}: {e}")

        return total_lines, total_files

    def list_filtered_py_files(self):
        """Return a list of Python files that should be included based on the exclusion rules."""
        return self.list_py_files([self.root])


if __name__ == "__main__":    
    load_dotenv()
    
    workspace_path = (
        Path("/home/jovyan/mordovets/agent-as-a-judge/benchmark/workspaces/OpenHands/39_Drug_Response_Prediction_SVM_GDSC_ML")
    )
    judge_path = (
        Path("/home/jovyan/mordovets/agent-as-a-judge/benchmark/judgement/OpenHands/39_Drug_Response_Prediction_SVM_GDSC_ML")
    )
    judge_path.mkdir(parents=True, exist_ok=True)
    sample_name = os.path.basename(os.path.normpath(workspace_path))

    dev_graph = DevGraph(
        root=workspace_path,
        # include_dirs=['src', 'results', 'models', 'data'],
        exclude_dirs=["__pycache__", "env", "venv", "node_modules", "dist", "build"],
        exclude_files=[".git", ".vscode", ".DS_Store"],
    )

    # all_files = dev_graph.list_all_files(workspace_path)
    py_files = dev_graph.list_py_files([workspace_path])
    tags, G = dev_graph.build(py_files)
    print(G)
    with open(os.path.join(judge_path, "graph.pkl"), "wb") as f:
        pickle.dump(G, f)

    with open(os.path.join(judge_path, "graph.pkl"), "rb") as f:
        try:
            G = pickle.load(f)
        except EOFError:
            G = nx.MultiDiGraph()
    dev_graph.save_file_structure(
        workspace_path, os.path.join(judge_path, "tree_structure.json")
    )

    tags_data = []
    for tag in tags:
        tags_data.append(
            {
                "file_path": tag.fname,
                "relative_file_path": tag.rel_fname,
                "line_number": tag.line,
                "name": tag.name,
                "identifier": tag.identifier,
                "category": tag.category,
                "details": tag.details,
            }
        )

    with open(os.path.join(judge_path, "tags.json"), "w") as f:
        json.dump(tags_data, f, indent=4)
        json_data = json.dumps(tags_data, indent=4)
        with open(os.path.join(judge_path, "tags.json"), "w") as f:
            f.write(json_data)

    pos = nx.spring_layout(G)
    labels = {}
    for node in G.nodes(data=True):
        node_name = node[0]
        node_data = node[1]

        filename = os.path.basename(node_data.get("fname", ""))
        label = f"{filename}:{node_name}"

        if node_data.get("category") == "class":
            label = f"{filename}:class {node_name}"
        elif node_data.get("category") == "function":
            label = f"{filename}:def {node_name}"

        labels[node_name] = label

    node_colors = []
    for node in G.nodes(data=True):
        category = node[1].get("category")
        if category == "class":
            node_colors.append("lightgreen")
        elif category == "function":
            node_colors.append("lightblue")
        else:
            node_colors.append("gray")

    nx.draw_networkx_nodes(G, pos, node_color=node_colors, node_size=300)
    nx.draw_networkx_edges(G, pos, edge_color="gray")
    nx.draw_networkx_labels(G, pos, labels=labels, font_color="black", font_size=8)
    plt.title("Simplified Code Graph Visualization")
    plt.axis("off")
    plt.show()
