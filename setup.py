#!/usr/bin/env python3
"""
memShare Interactive Setup

Guides you through setting up memShare step by step.
Creates the data directory, copies templates, and configures storage backend.

Usage:
    python setup.py           # Interactive setup
    python setup.py --quick   # Quick setup with defaults
"""

import os
import sys
import shutil
from pathlib import Path


# ANSI colors
class C:
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    END = "\033[0m"


def banner():
    print(f"""
{C.CYAN}{C.BOLD}
╔══════════════════════════════════════════╗
║          memShare Setup Wizard           ║
║   Shared Memory System for AI Agents    ║
╚══════════════════════════════════════════╝
{C.END}""")


def ask(prompt: str, default: str = "") -> str:
    """Ask user for input with a default value."""
    if default:
        result = input(f"{C.BLUE}  {prompt} [{default}]: {C.END}").strip()
        return result or default
    return input(f"{C.BLUE}  {prompt}: {C.END}").strip()


def ask_choice(prompt: str, choices: list, default: int = 0) -> str:
    """Ask user to choose from a list."""
    print(f"\n{C.BOLD}  {prompt}{C.END}")
    for i, choice in enumerate(choices):
        marker = " → " if i == default else "   "
        print(f"  {marker}{C.CYAN}[{i + 1}]{C.END} {choice}")
    while True:
        result = input(f"\n{C.BLUE}  Choose (1-{len(choices)}) [{default + 1}]: {C.END}").strip()
        if not result:
            return choices[default]
        try:
            idx = int(result) - 1
            if 0 <= idx < len(choices):
                return choices[idx]
        except ValueError:
            pass
        print(f"  {C.RED}Invalid choice, try again.{C.END}")


def setup_interactive():
    """Interactive setup flow."""
    banner()
    print(f"{C.GREEN}  Let's set up memShare for your AI agents!{C.END}\n")

    # Step 1: Data directory
    print(f"\n{C.BOLD}Step 1: Data Directory{C.END}")
    print(f"  Where should memShare store memory files?")
    data_dir = ask("Data directory", "~/memshare-data")
    data_dir = os.path.expanduser(data_dir)

    # Step 2: Storage backend
    print(f"\n{C.BOLD}Step 2: Storage Backend{C.END}")
    print(f"  How do you want to sync memories across devices?")
    backend_choices = [
        "local - Local storage only (single device)",
        "cos - Tencent Cloud COS (sync across devices)",
        "s3 - AWS S3 / S3-compatible (sync across devices)",
    ]
    backend = ask_choice("Storage backend:", backend_choices, 0).split(" - ")[0]

    # Step 3: Agent identity
    print(f"\n{C.BOLD}Step 3: Agent Identity{C.END}")
    agent_name = ask("Agent name (used for mailbox)", "my-agent")

    # Step 4: AI tool
    print(f"\n{C.BOLD}Step 4: AI Tool Integration{C.END}")
    tool_choices = [
        "CodeBuddy (Tencent)",
        "Cursor",
        "Windsurf (Codeium)",
        "Claude Desktop",
        "Other / Manual",
    ]
    tool = ask_choice("Which AI tool do you use?", tool_choices, 0)

    # Collect cloud storage credentials if needed
    env_vars = {
        "MEMSHARE_STORAGE": backend,
        "MEMSHARE_DATA_DIR": data_dir,
        "AGENT_NAME": agent_name,
    }

    if backend == "cos":
        print(f"\n{C.BOLD}Step 5: Tencent Cloud COS Configuration{C.END}")
        print(f"  {C.YELLOW}These credentials will be stored in .env (never committed to git){C.END}")
        env_vars["COS_SECRET_ID"] = ask("COS Secret ID")
        env_vars["COS_SECRET_KEY"] = ask("COS Secret Key")
        env_vars["COS_BUCKET"] = ask("COS Bucket name")
        env_vars["COS_REGION"] = ask("COS Region", "ap-guangzhou")
    elif backend == "s3":
        print(f"\n{C.BOLD}Step 5: AWS S3 Configuration{C.END}")
        print(f"  {C.YELLOW}These credentials will be stored in .env (never committed to git){C.END}")
        env_vars["AWS_ACCESS_KEY_ID"] = ask("AWS Access Key ID")
        env_vars["AWS_SECRET_ACCESS_KEY"] = ask("AWS Secret Access Key")
        env_vars["S3_BUCKET"] = ask("S3 Bucket name")
        env_vars["S3_REGION"] = ask("S3 Region", "us-east-1")

    # Execute setup
    print(f"\n{C.BOLD}{'=' * 50}{C.END}")
    print(f"{C.GREEN}  Setting up memShare...{C.END}\n")

    # Create data directory
    data_path = Path(data_dir)
    data_path.mkdir(parents=True, exist_ok=True)
    print(f"  ✓ Created data directory: {data_dir}")

    # Copy templates
    template_dir = Path(__file__).parent / "templates"
    if template_dir.exists():
        for item in template_dir.rglob("*"):
            if item.is_file():
                rel = item.relative_to(template_dir)
                dest = data_path / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not dest.exists():
                    shutil.copy2(item, dest)
                    print(f"  ✓ Created: {rel}")
                else:
                    print(f"  - Skipped (exists): {rel}")
    else:
        print(f"  {C.YELLOW}⚠ Templates directory not found, creating minimal structure{C.END}")
        for d in ["daily-memories", ".learnings", "mailbox/to-" + agent_name]:
            (data_path / d).mkdir(parents=True, exist_ok=True)

    # Create mailbox directory for this agent
    mailbox_dir = data_path / "mailbox" / f"to-{agent_name}"
    mailbox_dir.mkdir(parents=True, exist_ok=True)
    print(f"  ✓ Created mailbox: mailbox/to-{agent_name}/")

    # Update IDENTITY.md with agent name
    identity_file = data_path / "IDENTITY.md"
    if identity_file.exists():
        content = identity_file.read_text()
        content = content.replace("my-agent", agent_name)
        identity_file.write_text(content)
        print(f"  ✓ Updated IDENTITY.md with agent name: {agent_name}")

    # Write .env file
    env_file = Path(__file__).parent / ".env"
    with open(env_file, "w") as f:
        f.write("# memShare Configuration (auto-generated)\n")
        f.write(f"# Generated at: {__import__('datetime').datetime.now().isoformat()}\n\n")
        for k, v in env_vars.items():
            f.write(f"{k}={v}\n")
    print(f"  ✓ Created .env configuration")

    # Print next steps
    print(f"\n{C.BOLD}{'=' * 50}{C.END}")
    print(f"{C.GREEN}{C.BOLD}  ✅ memShare setup complete!{C.END}\n")

    print(f"  {C.BOLD}Next steps:{C.END}")
    print(f"  1. Add the memShare rule to your AI tool:")

    tool_name = tool.split(" (")[0].split(" /")[0].lower().replace(" ", "-")
    adapter_file = Path(__file__).parent / "adapters" / f"{tool_name}.md"
    if adapter_file.exists():
        print(f"     → See: adapters/{tool_name}.md")
    else:
        print(f"     → See: adapters/generic.md")

    if backend != "local":
        print(f"  2. Set up automatic sync (crontab):")
        script_path = Path(__file__).parent / "scripts"
        print(f"     * * * * * cd {data_dir} && python3 {script_path}/sync.py pull")
        print(f"     */5 * * * * cd {data_dir} && python3 {script_path}/sync.py push")

    print(f"  {'3' if backend != 'local' else '2'}. Schedule daily memory consolidation:")
    print(f"     0 23 * * * python3 {Path(__file__).parent}/scripts/memory_consolidator.py all")

    print(f"\n  {C.CYAN}Data directory: {data_dir}{C.END}")
    print(f"  {C.CYAN}Agent name: {agent_name}{C.END}")
    print(f"  {C.CYAN}Storage backend: {backend}{C.END}\n")


def setup_quick():
    """Quick setup with all defaults."""
    data_dir = os.path.expanduser("~/memshare-data")
    data_path = Path(data_dir)
    data_path.mkdir(parents=True, exist_ok=True)

    # Copy templates
    template_dir = Path(__file__).parent / "templates"
    if template_dir.exists():
        for item in template_dir.rglob("*"):
            if item.is_file():
                rel = item.relative_to(template_dir)
                dest = data_path / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not dest.exists():
                    shutil.copy2(item, dest)

    # Create default directories
    for d in ["daily-memories", ".learnings", "mailbox/to-my-agent"]:
        (data_path / d).mkdir(parents=True, exist_ok=True)

    # Write default .env
    env_file = Path(__file__).parent / ".env"
    with open(env_file, "w") as f:
        f.write("MEMSHARE_STORAGE=local\n")
        f.write(f"MEMSHARE_DATA_DIR={data_dir}\n")
        f.write("AGENT_NAME=my-agent\n")

    print(f"✅ memShare quick setup complete!")
    print(f"   Data directory: {data_dir}")
    print(f"   See adapters/ for AI tool integration guides.")


def main():
    if "--quick" in sys.argv:
        setup_quick()
    else:
        setup_interactive()


if __name__ == "__main__":
    main()
