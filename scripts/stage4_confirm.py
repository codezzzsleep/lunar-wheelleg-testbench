"""短确认：先写绑定决策，再对改变后的选择做真值执行（不重跑融合）。"""
import argparse
import hashlib
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import v3_core  # noqa: E402


def sha(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dir', required=True)
    ap.add_argument('--state', required=True)
    a = ap.parse_args()
    out = (ROOT / a.dir).resolve()
    state_dir = (ROOT / a.state).resolve()
    reagg = json.loads((out / 'reaggregate_frozen.json').read_text())
    st = json.loads((state_dir / 'state.json').read_text())
    dec = {'schema': 'stage4-decision-confirm/v1', 'state_id': st.get('state_id'),
           'frozen_actions': reagg['frozen_actions'],
           'excluded': reagg.get('excluded', []),
           'matrix_FULL_sha256': sha(out / 'matrix_FULL.jsonl'),
           'matrix_OBS_sha256': sha(out / 'matrix_OBS.jsonl'),
           'snapshot_state_hash': st.get('state_hash'),
           'chosen': {'FULL': reagg['FULL_new'], 'OBS': reagg['OBS_new']},
           'action_params': None,
           'written_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
           'written_before_exec': True}
    (out / 'decision_confirm.json').write_text(json.dumps(dec, ensure_ascii=False, indent=2))
    proto = json.loads((ROOT / 'plans/v3_protocol.json').read_text())
    core = v3_core.load_state(state_dir)
    ex = {}
    for arm in ('FULL', 'OBS'):
        act = dec['chosen'][arm]
        r = v3_core.truth_execute(core, act, proto, out / 'truth_exec_confirm', arm,
                                  budget=float(__import__('stage4_config').budget()))
        ex[arm] = {'action': act, 'outcome': r.get('outcome'),
                   'reason': r.get('reason'), 't_end': r.get('t_end'),
                   'final_x': r.get('final_x')}
    (out / 'execution_confirm.json').write_text(json.dumps(
        {'schema': 'stage4-execution-confirm/v1', 'state_id': st.get('state_id'),
         'decision_sha256': sha(out / 'decision_confirm.json'),
         'exec': ex}, ensure_ascii=False, indent=2))
    print(json.dumps({'state': st.get('state_id'), 'chosen': dec['chosen'],
                      'exec': ex}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
