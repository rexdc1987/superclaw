# Ma Chao Phase 4 - Workflow YAML Engine + CLI Integration

> Dispatched by Cao Cao | Date: 2026-06-20
> Final phase: connect all modules through YAML workflow files
> Output: src/rpa/workflow/ + docs/learning_machao_phase4.md

---

## Goals

1. Build YAML workflow parser that connects DAG + Adapters
2. Build workflow runner that executes YAML-defined pipelines
3. Integrate with CLI (superclaw run workflow.yaml)

## Tasks

### Task 1: Workflow YAML Schema
**Output**: src/rpa/workflow/schema.py + src/rpa/workflow/parser.py

Define and parse workflow YAML format:
- Schema: name, steps[], each step has action/adapter/params/conditions
- Parse YAML into DAG nodes and edges
- Validate: required fields, adapter existence, action existence
- Support variables: {{account.platform}}, {{config.target_url}}

Example workflow:
    name: douyin_engagement
    steps:
      - action: douyin.login
        params: {account: "{{account}}"}
      - action: douyin.search
        params: {keyword: "AI", limit: 10}
      - action: douyin.comment
        params: {template: "Great post!"}
        condition: "{{item.likes}} > 100"

### Task 2: Workflow Runner
**Output**: src/rpa/workflow/runner.py

Execute parsed workflows:
- Load workflow YAML -> parse -> build DAG -> execute
- Integrate with AccountPool for account selection
- Integrate with MetricsCollector for stats
- Integrate with AlertEngine for error alerts
- Support dry-run mode (validate without executing)

### Task 3: CLI Integration
**Output**: Update src/rpa/cli/commands/run.py

Connect workflow runner to CLI:
- superclaw run workflow.yaml --account default --dry-run
- superclaw run workflow.yaml --account default --watch
- Progress bar during execution
- Summary table after completion

### Task 4: Learning Notes
**Output**: docs/learning_machao_phase4.md

Document workflow engine design, YAML schema, integration patterns.

## Acceptance Criteria

1. YAML parser correctly converts workflow to DAG
2. Workflow runner executes all steps in order
3. CLI can run a workflow file end-to-end
4. Dry-run mode validates without executing
5. Write TASK_COMPLETE phase4_workflow at end of notes
