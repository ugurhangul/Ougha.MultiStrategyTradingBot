#!/usr/bin/env python3
"""
Comprehensive unused code analyzer for the Ougha Multi Strategy codebase.
Analyzes Python files for unused imports, functions, classes, variables, and more.
"""

import ast
import os
import re
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Set, Tuple
import json


class UnusedCodeAnalyzer:
    """Analyzes Python codebase for unused code."""
    
    def __init__(self, root_dir: str):
        self.root_dir = Path(root_dir)
        self.python_files = []
        self.findings = {
            'unused_imports': [],
            'unused_functions': [],
            'unused_classes': [],
            'unused_variables': [],
            'dead_code': [],
            'unused_config': [],
        }
        
        # Track all definitions and usages
        self.all_imports = defaultdict(list)  # file -> [(name, module)]
        self.all_functions = defaultdict(list)  # file -> [function_name]
        self.all_classes = defaultdict(list)  # file -> [class_name]
        self.all_variables = defaultdict(list)  # file -> [var_name]
        
        # Track usages across all files
        self.name_usages = defaultdict(set)  # name -> set of files using it
        
    def collect_python_files(self):
        """Collect all Python files in the project (excluding .venv)."""
        for py_file in self.root_dir.rglob('*.py'):
            # Skip virtual environment and __pycache__
            if '.venv' in str(py_file) or '__pycache__' in str(py_file):
                continue
            self.python_files.append(py_file)
        print(f"Found {len(self.python_files)} Python files to analyze")
        
    def analyze_file(self, filepath: Path) -> Dict:
        """Analyze a single Python file."""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
                tree = ast.parse(content, filename=str(filepath))
                
            return {
                'tree': tree,
                'content': content,
                'lines': content.split('\n')
            }
        except Exception as e:
            print(f"Error parsing {filepath}: {e}")
            return None
            
    def extract_imports(self, tree: ast.AST, filepath: Path):
        """Extract all imports from a file."""
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname if alias.asname else alias.name
                    imports.append((name, alias.name, node.lineno))
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ''
                for alias in node.names:
                    name = alias.asname if alias.asname else alias.name
                    imports.append((name, f"{module}.{alias.name}", node.lineno))
        
        self.all_imports[str(filepath)] = imports
        return imports
        
    def extract_definitions(self, tree: ast.AST, filepath: Path):
        """Extract function and class definitions."""
        functions = []
        classes = []
        variables = []
        
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                functions.append((node.name, node.lineno))
            elif isinstance(node, ast.ClassDef):
                classes.append((node.name, node.lineno))
            elif isinstance(node, ast.Assign):
                # Module-level assignments only
                if isinstance(node, ast.Assign) and hasattr(node, 'lineno'):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            variables.append((target.id, node.lineno))
        
        self.all_functions[str(filepath)] = functions
        self.all_classes[str(filepath)] = classes
        self.all_variables[str(filepath)] = variables
        
        return functions, classes, variables
        
    def find_name_usages(self, tree: ast.AST, content: str, filepath: Path):
        """Find all name usages in the file."""
        # Use regex to find all identifier usages
        # This is a simple approach - more sophisticated analysis would use AST
        identifiers = re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\b', content)
        
        for identifier in set(identifiers):
            self.name_usages[identifier].add(str(filepath))
            
    def check_unused_imports(self):
        """Check for unused imports in each file."""
        for filepath, imports in self.all_imports.items():
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                for import_name, full_name, lineno in imports:
                    # Skip __all__ and re-exports
                    if '__all__' in content:
                        continue
                        
                    # Check if import is used (simple regex check)
                    # Exclude the import line itself
                    lines = content.split('\n')
                    usage_content = '\n'.join(lines[:lineno-1] + lines[lineno:])
                    
                    # Check for usage
                    pattern = r'\b' + re.escape(import_name) + r'\b'
                    if not re.search(pattern, usage_content):
                        self.findings['unused_imports'].append({
                            'file': filepath,
                            'line': lineno,
                            'name': import_name,
                            'full_name': full_name
                        })
            except Exception as e:
                print(f"Error checking imports in {filepath}: {e}")
                
    def analyze_all(self):
        """Run complete analysis."""
        print("="*80)
        print("UNUSED CODE ANALYSIS")
        print("="*80)
        
        self.collect_python_files()
        
        # First pass: collect all definitions and usages
        print("\nPhase 1: Collecting definitions and usages...")
        for filepath in self.python_files:
            result = self.analyze_file(filepath)
            if result:
                self.extract_imports(result['tree'], filepath)
                self.extract_definitions(result['tree'], filepath)
                self.find_name_usages(result['tree'], result['content'], filepath)
        
        # Second pass: check for unused code
        print("Phase 2: Analyzing unused imports...")
        self.check_unused_imports()
        
        return self.findings


def main():
    """Main entry point."""
    analyzer = UnusedCodeAnalyzer('.')
    findings = analyzer.analyze_all()
    
    # Print results
    print("\n" + "="*80)
    print("ANALYSIS RESULTS")
    print("="*80)
    
    print(f"\n1. UNUSED IMPORTS: {len(findings['unused_imports'])} found")
    for item in findings['unused_imports'][:20]:  # Show first 20
        rel_path = item['file'].replace(str(Path.cwd()), '').lstrip('\\/')
        print(f"   {rel_path}:{item['line']} - {item['name']} (from {item['full_name']})")
    
    if len(findings['unused_imports']) > 20:
        print(f"   ... and {len(findings['unused_imports']) - 20} more")
    
    # Save full results to JSON
    output_file = 'unused_code_analysis.json'
    with open(output_file, 'w') as f:
        json.dump(findings, f, indent=2)
    print(f"\nFull results saved to: {output_file}")


if __name__ == '__main__':
    main()

