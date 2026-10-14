---
max_turns: 200
timeout_seconds: 2400
---

/congoforce:run requirements/text-stats-cli.md --id text-stats --auto-approve --set create_pr=false --set architecture_diagram=always --set models.spec=opus --set models.build=sonnet
