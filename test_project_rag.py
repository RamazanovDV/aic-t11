#!/usr/bin/env python3
"""Test script for Project RAG functionality."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_imports():
    """Test that all modules can be imported."""
    print("Testing imports...")
    
    try:
        from synth.app.project_rag import ProjectRAGIndexer, ProjectRAGSearch, ProjectRAGManager
        print("  - project_rag modules: OK")
    except Exception as e:
        print(f"  - project_rag modules: FAILED - {e}")
        return False
    
    try:
        from synth.app.handlers.chat_handler import parse_slash_command, SlashCommandHandler
        print("  - chat_handler with slash commands: OK")
    except Exception as e:
        print(f"  - chat_handler with slash commands: FAILED - {e}")
        return False
    
    try:
        from synth.app.routes_project import project_rag_bp
        print("  - routes_project blueprint: OK")
    except Exception as e:
        print(f"  - routes_project blueprint: FAILED - {e}")
        return False
    
    return True

def test_parse_slash_command():
    """Test slash command parsing."""
    print("\nTesting slash command parsing...")
    
    from synth.app.handlers.chat_handler import parse_slash_command
    
    # Test /help
    cmd, args, msg = parse_slash_command("/help")
    assert cmd == "help", f"Expected 'help', got '{cmd}'"
    assert args == "", f"Expected '', got '{args}'"
    print("  - /help: OK")
    
    # Test /help with args
    cmd, args, msg = parse_slash_command("/help что это за проект")
    assert cmd == "help", f"Expected 'help', got '{cmd}'"
    assert args == "что это за проект", f"Expected 'что это за проект', got '{args}'"
    print("  - /help with args: OK")
    
    # Test /project
    cmd, args, msg = parse_slash_command("/project /home/user/myproject")
    assert cmd == "project", f"Expected 'project', got '{cmd}'"
    assert args == "/home/user/myproject", f"Expected '/home/user/myproject', got '{args}'"
    print("  - /project: OK")
    
    # Test /index
    cmd, args, msg = parse_slash_command("/index")
    assert cmd == "index", f"Expected 'index', got '{cmd}'"
    print("  - /index: OK")
    
    # Test non-command message
    cmd, args, msg = parse_slash_command("Привет, как дела?")
    assert cmd is None, f"Expected None, got '{cmd}'"
    print("  - non-command message: OK")
    
    return True

def test_slash_command_handler():
    """Test SlashCommandHandler."""
    print("\nTesting SlashCommandHandler...")
    
    from synth.app.handlers.chat_handler import SlashCommandHandler
    
    commands = SlashCommandHandler.get_available_commands()
    assert len(commands) >= 3, f"Expected at least 3 commands, got {len(commands)}"
    
    command_names = [c["command"] for c in commands]
    assert "help" in command_names, "'help' command not found"
    assert "index" in command_names, "'index' command not found"
    assert "project" in command_names, "'project' command not found"
    
    print(f"  - Found {len(commands)} commands: {', '.join(command_names)}")
    
    return True

def test_project_rag_indexer():
    """Test ProjectRAGIndexer."""
    print("\nTesting ProjectRAGIndexer...")
    
    from synth.app.project_rag.indexer import ProjectRAGIndexer
    from pathlib import Path
    import tempfile
    
    # Create a test project
    with tempfile.TemporaryDirectory() as tmpdir:
        project_path = Path(tmpdir) / "test_project"
        project_path.mkdir()
        
        # Create README
        (project_path / "README.md").write_text("# Test Project\n\nThis is a test project.")
        
        # Create docs directory
        docs_dir = project_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "guide.md").write_text("# Guide\n\nThis is a guide.")
        
        # Test indexing
        indexer = ProjectRAGIndexer()
        result = indexer.index_project(str(project_path))
        
        assert result["success"], f"Indexing failed: {result}"
        assert result["indexed"]["readme"] >= 1, "README not indexed"
        assert result["indexed"]["docs"] >= 1, "docs not indexed"
        
        print(f"  - Indexed: README={result['indexed']['readme']}, "
              f"docs={result['indexed']['docs']}")
    
    return True

def test_project_rag_search():
    """Test ProjectRAGSearch."""
    print("\nTesting ProjectRAGSearch...")
    
    from synth.app.project_rag.search import ProjectRAGSearch
    from pathlib import Path
    import tempfile
    
    # Create a test project
    with tempfile.TemporaryDirectory() as tmpdir:
        project_path = Path(tmpdir) / "test_project"
        project_path.mkdir()
        
        # Create README
        (project_path / "README.md").write_text("# Test Project\n\nThis is a test project for testing.")
        
        # Index first
        from synth.app.project_rag.indexer import ProjectRAGIndexer
        indexer = ProjectRAGIndexer()
        indexer.index_project(str(project_path))
        
        # Test search
        search = ProjectRAGSearch()
        results = search.search(
            query="test",
            doc_types=["readme"],
            project_path=str(project_path),
            limit=5
        )
        
        assert len(results) > 0, "No results found"
        assert "test" in results[0].content.lower(), "Expected 'test' in content"
        
        print(f"  - Found {len(results)} results for 'test'")
    
    return True

def main():
    """Run all tests."""
    print("=" * 60)
    print("Project RAG Test Suite")
    print("=" * 60)
    
    tests = [
        ("Imports", test_imports),
        ("Slash Command Parsing", test_parse_slash_command),
        ("SlashCommandHandler", test_slash_command_handler),
        ("ProjectRAGIndexer", test_project_rag_indexer),
        ("ProjectRAGSearch", test_project_rag_search),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        try:
            if test_func():
                passed += 1
                print(f"\n[PASS] {name}")
            else:
                failed += 1
                print(f"\n[FAIL] {name}")
        except Exception as e:
            failed += 1
            print(f"\n[ERROR] {name}: {e}")
    
    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    return failed == 0

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
