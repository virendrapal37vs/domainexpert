"""Static graph inspection only: no executor, credentials or transport imports."""
from services.flow_workflow_validator import validate_workflow


def inspect_draft(payload):
    errors = validate_workflow(payload, strict=True)
    # Never echo node data or validator received values (may contain secrets).
    issues = [{key: item[key] for key in ('path', 'code', 'message') if key in item}
              for item in errors]
    steps = []
    if not errors:
        nodes = payload['nodes']
        outgoing = {node['id']: [] for node in nodes}
        degree = {node['id']: 0 for node in nodes}
        lookup = {node['id']: node for node in nodes}
        for edge in payload['edges']:
            outgoing[edge['source']].append(edge['target'])
            degree[edge['target']] += 1
        queue = [node['id'] for node in nodes if degree[node['id']] == 0]
        for ident in queue:
            steps.append({'node_id': ident, 'type': lookup[ident]['type']})
            for target in outgoing[ident]:
                degree[target] -= 1
                if degree[target] == 0:
                    queue.append(target)
    return {'valid': not errors, 'issues': issues, 'steps': steps,
            'executed': False,
            'notice': 'Static inspection only. Branches are possibilities, not predicted results. No broker requests or orders were sent.'}
