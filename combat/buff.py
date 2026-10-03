"""状态效果Buff系统"""
import random
from dataclasses import dataclass, field
from typing import Optional


# 持续伤害的攻击力基准：tick_damage 按 攻击力/基准 等比缩放
DOT_ATTACK_BASELINE = 100.0
# 状态效果键（非数值属性）
STATUS_KEYS = {"stunned", "stun", "silenced", "silence", "frozen", "immune"}


@dataclass
class Buff:
    id: str
    name: str
    duration: float  # 剩余持续时间
    max_duration: float
    stack_count: int = 1
    max_stacks: int = 1
    is_debuff: bool = False
    is_dispellable: bool = True
    source: str = ""
    effects: dict = field(default_factory=dict)  # {"attack": 10, "defense": -5}
    tick_interval: float = 0.0  # 周期效果间隔，0表示无周期效果
    tick_damage: float = 0.0  # 每次周期伤害
    last_tick_time: float = 0.0
    # 持续伤害类型（poison/burn 等），用于查抗性；为空时回退到 buff.id
    dot_type: str = ""
    # 额外攻击力加成比例（dot = tick_damage * 攻击力缩放 + attack * attack_ratio）
    attack_ratio: float = 0.0
    crit_chance: float = 0.0
    crit_multiplier: float = 1.5
    # 每层独立的剩余持续时间（堆叠衰减）与每层来源
    stack_durations: list = field(default_factory=list)
    stack_sources: list = field(default_factory=list)

    def power(self) -> float:
        """Buff强度，用于强/弱Buff覆盖判定"""
        total = self.tick_damage
        for key, value in self.effects.items():
            if isinstance(value, (int, float)) and key not in STATUS_KEYS:
                total += abs(float(value))
        return total

    def is_status(self, key: str) -> bool:
        return bool(self.effects.get(key))


class BuffSystem:
    def __init__(self):
        self.buffs: list[Buff] = []
        self.base_stats: dict = {"attack": 100, "defense": 50, "speed": 10}
        # 各类型持续伤害抗性，0~1（也兼容 0~100 的百分数写法）
        self.resistances: dict = {"poison": 0.0, "burn": 0.0}
        self.current_time: float = 0.0

    def apply_buff(self, buff: Buff) -> bool:
        """添加Buff。

        - 相同ID的Buff堆叠而不是重复添加，堆叠数受 max_stacks 限制
        - 每层独立记录来源与持续时间（堆叠衰减）
        - 堆满时做强/弱覆盖：强者覆盖弱者，弱者被忽略
        """
        if buff is None:
            return False

        existing = self.get_buff_by_id(buff.id)
        if existing is None:
            buff.stack_count = 1
            buff.stack_durations = [float(buff.duration)]
            buff.stack_sources = [buff.source]
            buff.last_tick_time = self.current_time
            self.buffs.append(buff)
            return True

        if existing.stack_count < existing.max_stacks:
            existing.stack_count += 1
            existing.stack_durations.append(float(buff.duration))
            existing.stack_sources.append(buff.source)
            existing.duration = max(existing.stack_durations)
            existing.max_duration = max(existing.max_duration, buff.max_duration)
            existing.source = buff.source
            existing.last_tick_time = min(existing.last_tick_time, self.current_time)
            return True

        # 已达堆叠上限：按强度覆盖
        if buff.power() > existing.power():
            existing.name = buff.name
            existing.duration = float(buff.duration)
            existing.max_duration = buff.max_duration
            existing.max_stacks = buff.max_stacks
            existing.is_debuff = buff.is_debuff
            existing.is_dispellable = buff.is_dispellable
            existing.source = buff.source
            existing.effects = dict(buff.effects)
            existing.tick_interval = buff.tick_interval
            existing.tick_damage = buff.tick_damage
            existing.dot_type = buff.dot_type
            existing.attack_ratio = buff.attack_ratio
            existing.crit_chance = buff.crit_chance
            existing.crit_multiplier = buff.crit_multiplier
            existing.stack_count = 1
            existing.stack_durations = [float(buff.duration)]
            existing.stack_sources = [buff.source]
            existing.last_tick_time = self.current_time
            return True
        # 弱者不叠加；同强度刷新持续时间
        existing.stack_durations = [float(buff.duration) for _ in existing.stack_durations]
        existing.duration = float(buff.duration)
        return True

    def update_buffs(self, dt: float) -> list[dict]:
        """推进所有Buff。

        - 每层独立扣减持续时间（堆叠衰减），层数掉零则移除
        - 按 tick_interval 触发周期伤害（中毒/灼烧）
        - 到期自动移除，并通过返回事件通知调用方
        返回事件：{"type": "tick"/"expired", "id", "name", ...}
        """
        if dt < 0:
            return []
        self.current_time += dt
        events: list[dict] = []

        for buff in list(self.buffs):
            # 1) 每层独立衰减
            if not buff.stack_durations:
                buff.stack_durations = [float(buff.duration)] * max(buff.stack_count, 1)
            if not buff.stack_sources:
                buff.stack_sources = [buff.source] * len(buff.stack_durations)
            buff.stack_durations = [remaining - dt for remaining in buff.stack_durations]

            alive_sources = [
                source for remaining, source in
                zip(buff.stack_durations, buff.stack_sources) if remaining > 0
            ]
            buff.stack_durations = [remaining for remaining in buff.stack_durations if remaining > 0]
            buff.stack_sources = alive_sources
            buff.stack_count = len(buff.stack_durations)

            # 2) 到期处理
            if buff.stack_count == 0:
                buff.duration = 0.0
                events.append({
                    "type": "expired", "id": buff.id, "name": buff.name,
                    "source": buff.source,
                })
                self.buffs.remove(buff)
                continue

            buff.duration = max(buff.stack_durations)

            # 3) 周期效果（DoT）
            if buff.tick_interval > 0 and buff.tick_damage > 0:
                elapsed = self.current_time - buff.last_tick_time
                tick_count = int(elapsed // buff.tick_interval)
                if tick_count > 0:
                    buff.last_tick_time += tick_count * buff.tick_interval
                    for _ in range(tick_count):
                        is_crit = random.random() < buff.crit_chance
                        damage = self.calculate_dot(buff, is_crit=is_crit)
                        events.append({
                            "type": "tick",
                            "id": buff.id,
                            "name": buff.name,
                            "dot_type": buff.dot_type or buff.id,
                            "damage": damage,
                            "crit": is_crit,
                            "source": buff.source,
                        })

        return events

    def dispel_buff(self, buff_id: str) -> bool:
        """驱散指定ID的Buff（一次性驱散全部堆叠层）。

        is_dispellable=False 的关键/Boss Buff不可驱散。
        """
        buff = self.get_buff_by_id(buff_id)
        if buff is None or not buff.is_dispellable:
            return False
        self.buffs.remove(buff)
        return True

    def dispel_debuffs(self, count: int) -> list[str]:
        """按数量上限驱散减益Buff，最多驱散 count 个（每个含全部堆叠层）。

        不可驱散标记的Buff跳过。返回被驱散的Buff ID列表。
        """
        if count <= 0:
            return []
        removed: list[str] = []
        for buff in list(self.buffs):
            if len(removed) >= count:
                break
            if buff.is_debuff and buff.is_dispellable:
                self.buffs.remove(buff)
                removed.append(buff.id)
        return removed

    def apply_effects(self) -> dict:
        """汇总所有活跃Buff的效果：

        - 数值属性按堆叠层数加算
        - 状态效果（眩晕/沉默等）以布尔标记合并
        """
        modified = dict(self.base_stats)
        for buff in self.buffs:
            for stat, value in buff.effects.items():
                if stat in STATUS_KEYS or isinstance(value, bool):
                    modified[stat] = modified.get(stat, False) or bool(value)
                elif isinstance(value, (int, float)):
                    if stat in modified and not isinstance(modified[stat], bool):
                        modified[stat] += value * buff.stack_count
                    else:
                        modified[stat] = value * buff.stack_count
        return modified

    def has_status(self, status: str) -> bool:
        """是否处于某状态（如 stunned）"""
        return any(buff.is_status(status) for buff in self.buffs)

    def can_act(self) -> bool:
        """当前是否可以行动（眩晕/冰冻等状态下不可行动）"""
        return not any(
            buff.is_status(key)
            for buff in self.buffs
            for key in ("stunned", "stun", "frozen")
        )

    def modify_outgoing_damage(self, damage: float) -> float:
        """增伤Buff对出手伤害的修正（damage_dealt_pct 增伤百分比）"""
        bonus = sum(
            float(buff.effects.get("damage_dealt_pct", 0.0))
            for buff in self.buffs
        )
        return max(0.0, damage * (1.0 + bonus))

    def modify_incoming_damage(self, damage: float) -> float:
        """受伤修正：damage_taken_pct 增伤/易伤，damage_reduction_pct 减伤"""
        taken = sum(
            float(buff.effects.get("damage_taken_pct", 0.0))
            for buff in self.buffs
        )
        reduction = sum(
            float(buff.effects.get("damage_reduction_pct", 0.0))
            for buff in self.buffs
        )
        return max(0.0, damage * (1.0 + taken - reduction))

    def trigger_on_attacked(self, damage: float) -> list[dict]:
        """被攻击时触发的效果（如反伤）。

        effects 支持：
        - thorns: 固定反伤值（按堆叠层数）
        - thorns_pct: 按所受伤害百分比反伤
        """
        events: list[dict] = []
        for buff in self.buffs:
            thorns = float(buff.effects.get("thorns", 0.0)) * buff.stack_count
            thorns += float(buff.effects.get("thorns_pct", 0.0)) * damage
            if thorns > 0:
                events.append({
                    "type": "thorns",
                    "id": buff.id,
                    "name": buff.name,
                    "damage": thorns,
                    "source": buff.source,
                })
        return events

    def calculate_dot(self, buff: Buff, is_crit: Optional[bool] = None) -> float:
        """计算单次持续伤害。

        - 基础伤害随攻击力等比缩放，并可叠加 attack_ratio 的攻击力加成
        - 按堆叠层数倍增
        - 受对应类型抗性（毒抗/火抗）减免
        - 支持暴击（crit_chance/crit_multiplier）
        """
        attack = float(self.base_stats.get("attack", DOT_ATTACK_BASELINE))
        scaled = (
            buff.tick_damage * (attack / DOT_ATTACK_BASELINE)
            + attack * buff.attack_ratio
        )
        damage = scaled * max(buff.stack_count, 1)

        dot_key = buff.dot_type or buff.id
        resist = self._get_resistance(dot_key)
        damage *= 1.0 - resist

        if is_crit is None:
            is_crit = random.random() < buff.crit_chance
        if is_crit:
            damage *= buff.crit_multiplier
        return max(0.0, damage)

    def _get_resistance(self, dot_key: str) -> float:
        """读取抗性，兼容 0~1 与 0~100 两种写法，结果裁剪到 [0, 1]"""
        resist = self.resistances.get(dot_key)
        if resist is None:
            resist = self.base_stats.get(f"{dot_key}_resist")
        if resist is None:
            resist = self.base_stats.get(f"{dot_key}_resistance", 0.0)
        resist = float(resist or 0.0)
        if resist > 1.0:
            resist /= 100.0
        return min(1.0, max(0.0, resist))

    def get_buff_by_id(self, buff_id: str) -> Optional[Buff]:
        """根据ID获取Buff"""
        for buff in self.buffs:
            if buff.id == buff_id:
                return buff
        return None

    def remove_expired(self):
        """移除过期Buff（update_buffs 已自动移除，这里作为兜底）"""
        self.buffs = [
            b for b in self.buffs
            if b.duration > 0 and (not b.stack_durations or max(b.stack_durations) > 0)
        ]

    def get_active_buffs(self) -> list[Buff]:
        """获取所有活跃Buff"""
        return [b for b in self.buffs if b.duration > 0]
