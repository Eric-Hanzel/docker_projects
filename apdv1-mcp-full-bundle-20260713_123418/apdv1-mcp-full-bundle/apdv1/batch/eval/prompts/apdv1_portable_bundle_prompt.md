# Portable Bundle Cost Evaluation Task

The runner will provide one JSON object containing `url` and any extras.

Use the provided target to produce the final portable, reproducible delivery bundle for the project.

Required mode:

```text
delivery_mode=portable-deliverable
portable_final_required=true
```

Follow the APDv1 portable-deliverable workflow:

- use official installation/deployment information as guidance
- build and verify `Deliverable/<project_name>-final/`
- run only the final portable audit gate
- finish with a terminal task state

This is a cost/timing experiment. Do not switch to local-run mode and do not stop after a local deployment.
