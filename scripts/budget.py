"""
预算与任务账本（工作包 A）。

  from budget import BudgetLedger
  led = BudgetLedger('runs/unseen/generation/ledger.jsonl')

  ok, why = led.reserve(identity, attempt_id, credits_upper, budget)
  led.mark(attempt_id, 'submitted', task_id=123)
  rep = led.report(budget)

模型（不再是"进行中状态集合"）：
  · 已创建任务数   = 有 task_id 的记录数（**不**因状态变化而减少）
  · 占用费用上界   = 所有"已占用"记录的 estimate_upper 之和
  · 已占用 = 除「证明未发出」外的全部状态：planned/created/submitted/pending/
             succeeded/failed/uncertain/downloaded/invalid_asset
  · 释放只有一种依据：release_reason = 'never_sent'（并有证据字符串）
  · 实际扣费只有官方依据才写 actual_charge，否则 unknown

并发：reserve 在文件锁内完成"读-检查-写"，不会两个进程同时占到最后一格。
原子性：写临时文件 + os.replace；启动时校验每行 JSON 可解析。
身份：identity = 请求/缓存身份（64 位 hex）；attempt_id = 单次尝试唯一键。
"""
import fcntl
import json
import os
import pathlib
import time
import uuid

# ---- 状态 ----
ST_PLANNED = 'planned'          # 已预留，尚未发出
ST_CREATED = 'created'          # 已创建（有 task_id），但未确认状态
ST_SUBMITTED = 'submitted'
ST_PENDING = 'pending'
ST_SUCCEEDED = 'succeeded'
ST_FAILED = 'failed'
ST_UNCERTAIN = 'uncertain'      # 可能已发出但 task_id 未拿到
ST_DOWNLOADED = 'downloaded'
ST_INVALID = 'invalid_asset'
ST_RELEASED = 'released'        # 证明未发出，已释放

HELD = {ST_PLANNED, ST_CREATED, ST_SUBMITTED, ST_PENDING, ST_SUCCEEDED,
        ST_FAILED, ST_UNCERTAIN, ST_DOWNLOADED, ST_INVALID}
RELEASABLE = {ST_PLANNED}

VALID_NUM = (int, float)


def _valid_credits(v):
    """拒绝 NaN / inf / 负数 / 非数值。"""
    if not isinstance(v, VALID_NUM) or isinstance(v, bool):
        return False
    if v != v or v in (float('inf'), float('-inf')):
        return False
    return v >= 0


def atomic_write(path, text):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f'.tmp{os.getpid()}')
    with open(tmp, 'w') as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class Lock:
    def __init__(self, path):
        self.path = pathlib.Path(path)
        self.fh = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(self.path, 'a+')
        fcntl.flock(self.fh, fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        fcntl.flock(self.fh, fcntl.LOCK_UN)
        self.fh.close()


class BudgetLedger:
    def __init__(self, path):
        self.path = pathlib.Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lockpath = self.path.with_suffix(self.path.suffix + '.lock')

    # ---- 读 ----
    def rows(self):
        if not self.path.exists():
            return []
        out = []
        for i, line in enumerate(self.path.read_text().splitlines(), 1):
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise RuntimeError(f'账本第 {i} 行损坏：{e}') from None
        return out

    def is_held(self, r):
        return r.get('status') in HELD and not r.get('release_reason')

    def used_credits(self):
        return sum(float(r.get('estimate_upper') or 0)
                   for r in self.rows() if self.is_held(r))

    def used_tasks(self):
        """已创建任务数：有 task_id 的记录，**不**因下载完成而减少。"""
        seen = set()
        n = 0
        for r in self.rows():
            if not self.is_held(r):
                continue
            tid = r.get('task_id')
            key = tid if tid is not None else r.get('attempt_id')
            if key in seen:
                continue
            seen.add(key)
            n += 1
        return n

    def verified_charge(self):
        return sum(float(r['actual_charge']) for r in self.rows()
                   if r.get('actual_charge') is not None)

    def report(self, budget):
        held = self.used_credits()
        tasks = self.used_tasks()
        return {
            'created_tasks': tasks,
            'held_credits_upper': round(held, 3),
            'verified_charge': round(self.verified_charge(), 3),
            'charge_unknown': sum(1 for r in self.rows()
                                  if r.get('actual_charge') is None),
            'remaining_credits': round(float(budget['hard_cap']) - held, 3),
            'remaining_tasks': int(budget['max_create_tasks']) - tasks,
            'hard_cap': budget['hard_cap'],
            'per_task_cap': budget['per_task_cap'],
            'max_create_tasks': budget['max_create_tasks'],
        }

    # ---- 写 ----
    def reserve(self, identity, attempt_id, credits_upper, budget):
        """
        原子预留。检查与写入在同一临界区。
        返回 (ok, reason)。
        """
        if not _valid_credits(credits_upper):
            return False, f'非法费用上界 {credits_upper!r}'
        for k in ('hard_cap', 'per_task_cap', 'max_create_tasks'):
            if not _valid_credits(budget.get(k)):
                return False, f'非法预算参数 {k}={budget.get(k)!r}'
        if len(identity) != 64:
            return False, f'identity 必须是 64 位十六进制，收到长度 {len(identity)}'
        if credits_upper > float(budget['per_task_cap']):
            return False, f'单任务 {credits_upper} > 上限 {budget["per_task_cap"]}'
        with Lock(self.lockpath):
            rows = self.rows()
            # 同一 attempt_id 只能预留一次：重复提交/重放必须在预算层被挡住
            if any(r.get('attempt_id') == attempt_id for r in rows):
                return False, (f'attempt_id {attempt_id} 已存在：拒绝重复预留'
                               '（有意重复采样请使用新的 sample_id/attempt_id）')
            held_c = sum(float(r.get('estimate_upper') or 0)
                         for r in rows if self.is_held(r))
            seen = set()
            held_n = 0
            for r in rows:
                if not self.is_held(r):
                    continue
                key = r.get('task_id') if r.get('task_id') is not None else r.get('attempt_id')
                if key in seen:
                    continue
                seen.add(key)
                held_n += 1
            if held_c + credits_upper > float(budget['hard_cap']):
                return False, (f'积分将达 {held_c + credits_upper:.1f} '
                               f'> 上限 {budget["hard_cap"]}')
            if held_n + 1 > int(budget['max_create_tasks']):
                return False, f'任务数将达 {held_n + 1} > 上限 {budget["max_create_tasks"]}'
            rows.append({'identity': identity, 'attempt_id': attempt_id,
                         'status': ST_PLANNED, 'estimate_upper': float(credits_upper),
                         'actual_charge': None, 'verified': 'unknown',
                         'task_id': None, 'ts': time.time(),
                         'run_scope': budget.get('scope', 'unknown')})
            atomic_write(self.path, '\n'.join(json.dumps(r, ensure_ascii=False)
                                              for r in rows) + '\n')
            return True, 'reserved'

    def mark(self, attempt_id, status, **kw):
        """按 attempt_id 更新**单条**记录，不影响同 identity 的其他记录。"""
        if status not in HELD | {ST_RELEASED}:
            raise ValueError(f'未知状态 {status}')
        with Lock(self.lockpath):
            rows = self.rows()
            hit = 0
            for r in rows:
                if r.get('attempt_id') == attempt_id:
                    r['status'] = status
                    r.update(kw)
                    hit += 1
            if hit != 1:
                raise RuntimeError(f'attempt_id {attempt_id} 命中 {hit} 条（应为 1）')
            atomic_write(self.path, '\n'.join(json.dumps(r, ensure_ascii=False)
                                              for r in rows) + '\n')

    def release(self, attempt_id, reason):
        """释放预留，**仅**当能证明请求从未发出。"""
        with Lock(self.lockpath):
            rows = self.rows()
            for r in rows:
                if r.get('attempt_id') != attempt_id:
                    continue
                if r.get('status') not in RELEASABLE:
                    raise RuntimeError(
                        f'状态 {r["status"]} 不可释放：只有 planned 且证明未发出才可释放')
                r['status'] = ST_RELEASED
                r['release_reason'] = reason
                break
            else:
                raise RuntimeError(f'attempt_id {attempt_id} 不存在')
            atomic_write(self.path, '\n'.join(json.dumps(r, ensure_ascii=False)
                                              for r in rows) + '\n')


def new_attempt_id():
    return uuid.uuid4().hex
