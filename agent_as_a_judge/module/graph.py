import os
import re
import ast
import json
import pickle

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
from grep_ast import TreeContext
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

        relative_filepath_list = relative_filepath.split(os.sep)
        s = self._navigate_structure(relative_filepath_list)
        if s is None:
            return
        
        structure_classes, structure_all_funcs = self._extract_structure_info(s)
        
        lang = self.filename_to_lang(filepath)
        if not lang:
            return

        language = get_language(lang)
        parser = get_parser(lang)
        parser.set_language(language)

        code, codelines = self._read_code(filepath)
        if not code:
            return

        tree = parser.parse(bytes(code, "utf-8"))
        
        std_funcs, std_libs = [], []
        if lang == 'python':
            try:
                std_funcs, std_libs = self._std_proj_funcs(code, filepath)
            except Exception:
                pass

        builtins_funs = [name for name in dir(builtins)]
        builtins_funs += dir(list)
        builtins_funs += dir(dict)
        builtins_funs += dir(set)
        builtins_funs += dir(str)
        builtins_funs += dir(tuple)

        if lang == 'python':
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
        elif lang == 'typescript':
            query_scm = """
            (class_declaration
                (type_identifier) @definition.class)

            (lexical_declaration
                (variable_declarator
                    (identifier) @definition.function))

            (call_expression
                (identifier) @reference.call)
            """
        elif lang == 'c_sharp':
            query_scm = """
            (class_declaration
                (identifier) @definition.class)

            (method_declaration
                (identifier) @definition.function)

            (constructor_declaration
                (identifier) @definition.function)

            (local_declaration_statement) @reference.call

            (expression_statement) @reference.call

            (return_statement) @reference.call
            """
        else:
            return

        query = language.query(query_scm)
        captures = query.captures(tree.root_node)

        saw = set() 

        def_count = 0
        ref_count = 0

        for node, tag in captures:
            if tag.startswith("name.definition.") and lang == 'python':
                identifier = "def" 
                def_count += 1
            elif (tag.startswith("definition.function") or tag.startswith("definition.class")) and lang == 'typescript':
                identifier = "def"
                def_count += 1
            elif (tag.startswith("definition.function") or tag.startswith("definition.class")) and lang == 'c_sharp':
                identifier = "def"
                def_count += 1
                
            elif tag.startswith("name.reference.") and lang == 'python':
                identifier = "ref"
                ref_count += 1
            elif tag.startswith("reference.call") and lang == 'typescript':
                identifier = "ref"
                ref_count += 1
            elif tag.startswith("reference.call") and lang == 'c_sharp':
                identifier = "ref"
                ref_count += 1
            else:
                continue

            saw.add(identifier)

            cur_cdl = codelines[node.start_point[0]] 
            
            if lang == 'python':
                category = "class" if "class " in cur_cdl else "function"
                    
            elif lang == 'typescript':
                if 'class' in cur_cdl:
                    category = 'class'
                else:
                    category = 'function'
                    
            elif lang == 'c_sharp':
                if 'class' in cur_cdl:
                    category = 'class'
                else:
                    category = 'function' 
            else:
                category = 'function'

            tag_name = node.text.decode("utf-8") 
            if (
                tag_name in std_funcs
                or tag_name in std_libs
                or tag_name in builtins_funs
            ):
                continue

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
                        line_nums = [node.start_point[0]+1, node.end_point[0]+1]

                    result = Tag(
                        rel_fname=relative_filepath,
                        fname=filepath,
                        name=tag_name,
                        identifier=identifier,
                        category=category,
                        details="\n".join(class_functions),
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
                            "start_line", node.start_point[0]+1
                        ),
                        structure_all_funcs.get(tag_name, {}).get(
                            "end_line", node.end_point[0]+1
                        ),
                    ]
                else:
                    line_nums = [node.start_point[0]+1, node.end_point[0]+1]

                result = Tag(
                    rel_fname=relative_filepath,
                    fname=filepath,
                    name=tag_name,
                    identifier=identifier,
                    category=category,
                    details=cur_cdl,
                    line=line_nums,
                )

            if result:
                yield result

        if "ref" in saw or "def" not in saw:
            return 

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

    def filename_to_lang(self, filename):
        extension = os.path.splitext(filename)[1]
        if extension == '.py':
            return 'python'
        elif extension in ['.ts']:
            return 'typescript'
        elif extension in ['.cs']:
            return 'c_sharp'
        else:
            return None

    def _read_code(self, filepath):

        with open(filepath, "r", encoding="utf-8") as f:
            code = f.read()

        code = code.replace("\ufeff", "") 

        if not code:
            return "", []

        with open(str(filepath), "r", encoding="utf-8") as f:
            codelines = f.readlines()

        return code, codelines

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
                filepath = os.path.join(root, filename)
                if filepath not in main_file_set:
                    continue
                if filename.endswith(".py"):
                    class_info, function_names, code_lines = self.parse_python_file(
                        filepath
                    )
                    current_structure[filename] = {
                        "classes": class_info,
                        "functions": function_names,
                        "code": code_lines,
                    }
                elif filename.endswith(".tsx") or filename.endswith(".ts"):
                    class_info, function_names, code_lines = self.parse_typescript_file(
                        filepath
                    )
                    current_structure[filename] = {
                        "classes": class_info,
                        "functions": function_names,
                        "code": code_lines,
                    }
                elif filename.endswith(".cs"):
                    class_info, function_names, code_lines = self.parse_csharp_file(
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

    def parse_typescript_file(self, file_path, file_content=None):
        if file_content is None:
            try:
                with open(file_path, "r", encoding='utf-8') as file:
                    file_content = file.read()
                    file_content = file_content.replace("\ufeff", "") 
            except Exception as e:
                print(f"Error in file {file_path}: {e}")
                return [], [], ""
        code_lines = file_content.splitlines()

        language = get_language('typescript')
        parser = get_parser('typescript')
        parser.set_language(language)

        tree = parser.parse(bytes(file_content, 'utf-8'))
        
        class_info = []
        function_names = []
        class_methods = set()

        root_node = tree.root_node

        def check(root, depth):
            if root.children:
                for item in root.children:
                    check(item, depth+1)
        check(root_node, 0)
        
        def traverse(node):
            if node.type == 'class_declaration':
                class_name = None
                methods = []

                for child in node.children:
                    if child.type == 'type_identifier':
                        class_name = file_content[child.start_byte:child.end_byte]
                        break

                body_node = None
                for child in node.children:
                    if child.type == 'class_body':
                        body_node = child
                        break

                if body_node:
                    def extract_methods(body_node):
                        for item in body_node.children:
                            if item.type == 'method_definition':
                                func_name = None
                                for func_child in item.children:
                                    if func_child.type == 'property_identifier':
                                        func_name = file_content[func_child.start_byte:func_child.end_byte]
                                        break
                                if func_name:
                                    methods.append(
                                        {
                                            'name': func_name,
                                            'start_line': item.start_point[0]+1,
                                            'end_line': item.end_point[0]+1,
                                            'text': code_lines[item.start_point[0]: item.end_point[0]+1],
                                        }
                                    )
                                    class_methods.add(func_name)
                            # elif item.type == 'declaration':
                            #     extract_methods(item)
                    extract_methods(body_node)

                if class_name:
                    class_info.append(
                        {
                            'name': class_name,
                            'start_line': node.start_point[0]+1,
                            'end_line': node.end_point[0]+1,
                            'text': code_lines[node.start_point[0]: node.end_point[0]+1],
                            'methods': methods,
                        }
                    )
            elif node.type == 'lexical_declaration':
                func_name = None
                for child in node.children:
                    if child.type == 'variable_declarator':
                        for child_2 in child.children:
                            if child_2.type == 'identifier':
                                func_name = file_content[child_2.start_byte:child_2.end_byte]
                                break
                    if child.type == 'simple_identifier':
                        func_name = file_content[child.start_byte:child.end_byte]
                        break
                if func_name and func_name not in class_methods:
                    function_names.append(
                        {
                            'name': func_name,
                            'start_line': node.start_point[0]+1,
                            'end_line': node.end_point[0]+1,
                            'text': code_lines[node.start_point[0]: node.end_point[0]+1],
                        }
                    )
            for child in node.children:
                traverse(child)

        traverse(root_node)
        
        return class_info, function_names, code_lines

    def parse_csharp_file(self, file_path, file_content=None):
        if file_content is None:
            try:
                with open(file_path, "r", encoding='utf-8') as file:
                    file_content = file.read()
                    file_content = file_content.replace("\ufeff", "") 
                    file_content = re.sub(r'//.*', '', file_content)
            except Exception as e:
                print(f"Error in file {file_path}: {e}")
                return [], [], ""
        code_lines = file_content.splitlines()

        language = get_language('c_sharp')
        parser = get_parser('c_sharp')
        parser.set_language(language)
        
        tree = parser.parse(bytes(file_content, 'utf-8'))
        
        class_info = []
        function_names = []
        class_methods = set()

        root_node = tree.root_node

        
        def check(root, depth):
            if root.children:
                for item in root.children:
                    check(item, depth+1)
        check(root_node, 0)
        
        def traverse(node):
            if node.type == 'class_declaration':
                class_name = None
                methods = []

                for child in node.children:
                    if child.type == 'identifier':
                        class_name = file_content[child.start_byte:child.end_byte]
                        break

                body_node = None
                for child in node.children:
                    if child.type == 'declaration_list':
                        body_node = child
                        break

                if body_node:
                    def extract_methods(body_node):
                        for item in body_node.children:
                            if item.type == 'method_declaration' or item.type == 'constructor_declaration':
                                func_name = None
                                for func_child in item.children:
                                    if func_child.type == 'identifier':
                                        func_name = file_content[func_child.start_byte:func_child.end_byte]
                                        break
                                if func_name:
                                    methods.append(
                                        {
                                            'name': func_name,
                                            'start_line': item.start_point[0],
                                            'end_line': item.end_point[0],
                                            'text': code_lines[item.start_point[0]: item.end_point[0]+1],
                                        }
                                    )
                                    class_methods.add(func_name)
                            # elif item.type == 'declaration':
                            #     extract_methods(item)
                    extract_methods(body_node)

                if class_name:
                    class_info.append(
                        {
                            'name': class_name,
                            'start_line': node.start_point[0],
                            'end_line': node.end_point[0],
                            'text': code_lines[node.start_point[0]: node.end_point[0]+1],
                            'methods': methods,
                        }
                    )
            for child in node.children:
                traverse(child)

        traverse(root_node)
        
        return class_info, function_names, code_lines

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

            if this_rel_fname != cur_fname:
                if lois is not None:
                    output += "\n"
                    output += cur_fname + ":\n"
                    output += self.render_tree(cur_abs_fname, cur_fname, lois)
                    lois = None
                elif cur_fname:
                    output += "\n" + cur_fname + "\n"
                if isinstance(tag, Tag):
                    lois = []
                    cur_abs_fname = tag.fname
                cur_fname = this_rel_fname

            if lois is not None:
                lois.append(tag.line)

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

    def list_code_files(self, directories: List, extensions=None):
        if extensions is None:
            extensions = ['.py', '.ts', '.tsx', '.cs']
        files = []
        for directory in directories:
            if Path(directory).is_dir():
                files += self.list_all_files(
                    directory
                )
            else:
                files.append(directory)

        code_files = []
        for item in files:
            if not any(item.endswith(ext) for ext in extensions):
                continue
            code_files.append(item)
            
        return code_files

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
                            tree[relative_root][file] = None

            return tree

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

    def list_filtered_code_files(self):
        """Return a list of code files that should be included based on the exclusion rules."""
        return self.list_code_files([self.root])


if __name__ == "__main__":

    load_dotenv()

    workspace_path = Path("./benchmark/workspaces/OpenHands/Backend-main")
    judge_path = Path("./benchmark/judgement/OpenHands/Backend-main")
    
    judge_path.mkdir(parents=True, exist_ok=True)
    sample_name = os.path.basename(os.path.normpath(workspace_path))

    dev_graph = DevGraph(
        root=workspace_path,
        # include_dirs=['src', 'results', 'models', 'data'],
        exclude_dirs=["__pycache__", "env", "venv", "node_modules", "dist", "build", ".ipynb_checkpoints"],
        exclude_files=[".git", ".vscode", ".DS_Store"],
    )

    # all_files = dev_graph.list_all_files(workspace_path)
    py_files = dev_graph.list_code_files([str(workspace_path)])
    print('py_files', py_files)
    
    tags, G = dev_graph.build(py_files)
    # print('Tags', tags)
    print('G', G)
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
    plt.savefig('g.png')
    plt.show()
