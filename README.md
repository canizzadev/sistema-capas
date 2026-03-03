
# Agent Architecture Instance

This repository implements the 3-Layer Agent Architecture described in `agente.md`.

## Directory Structure

- `directives/`: Standard Operating Procedures (SOPs) in Markdown. These define *what* needs to be done.
- `execution/`: Deterministic Python scripts. These perform the *how*.
- `.tmp/`: Intermediate files and temporary data.

## Usage

1.  **Define a Directive**: Create a Markdown file in `directives/` that outlines the goal, inputs, and steps for a task.
2.  **Create an Execution Tool**: If no existing tool matches the need, create a Python script in `execution/` to handle the logic.
3.  **Run the Agent**: The agent (you) reads the directive and executes the corresponding tools.

## Example

Try running the example script:

```bash
python3 execution/hello_world.py
```

This should print a success message, confirming the environment is ready.
