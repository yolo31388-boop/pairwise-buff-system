"""状态效果Buff系统"""
import random
from dataclasses import dataclass, field
from typing import Optional


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
    effects: dict = field(default_factory=dict)  # {"attack": 10, "stunned": True}
    tick_interval: float = 0.0  # 周期效果间隔，0表示无周期效果
    tick_damage: float = 0.0  # 每次周期伤害
    last_tick_time: float = 0.0
    damage_modifier: float = 0.0  # 伤害修正比例，0.2 表示增伤20%
    reflect_ratio: float = 0.0  # 被攻击时的反伤比例
    crit_chance: float = 0.0  # 持续伤害暴击率
    crit_multiplier: float = 2.0  # 暴击倍率
    stack_timers: list = field(default_factory=list)  # 每层独立计时（堆叠衰减）

    def power(self) -> float:
        """Buff强度，用于强弱覆盖判断"""
        stat_power = sum(abs(v) for v in self.effects.values()
                         if isinstance(v, (int, float)) and not isinstance(v, bool))
        return stat_power + self.tick_damage + abs(self.damage_modifier) * 100


class BuffSystem:
    def __init__(self):
        self.buffs: list[Buff] = []
        self.base_stats: dict = {"attack": 100, "defense": 50, "speed": 10}
        self.current_time: float = 0.0

    def apply_buff(self, buff: Buff) -> bool:
        """添加Buff：检查相同Buff，堆叠/刷新，强Buff覆盖弱Buff，记录来源"""
        existing = self.get_buff_by_id(buff.id)
        if existing is None:
            if not buff.stack_timers:
                buff.stack_timers = [buff.duration] * buff.stack_count
            self.buffs.append(buff)
            return True
        # 相同Buff：堆叠并刷新持续时间，不超过层数上限
        if existing.stack_count < existing.max_stacks:
            existing.stack_count += 1
            existing.stack_timers.append(buff.duration)
        existing.duration = max(existing.duration, buff.duration)
        # 覆盖逻辑：只有更强或相等的新Buff才覆盖效果与来源
        if buff.power() >= existing.power():
            existing.effects = dict(buff.effects)
            existing.tick_damage = buff.tick_damage
            existing.tick_interval = buff.tick_interval
            existing.damage_modifier = buff.damage_modifier
            existing.reflect_ratio = buff.reflect_ratio
            if buff.source:
                existing.source = buff.source
        return True

    def update_buffs(self, dt: float) -> list[dict]:
        """更新Buff：扣持续时间、触发周期效果、堆叠衰减、到期移除"""
        self.current_time += dt
        events: list[dict] = []
        expired: list[Buff] = []
        for buff in list(self.buffs):
            buff.duration -= dt
            # 周期效果（tick）
            if buff.tick_interval > 0 and buff.tick_damage > 0 and buff.duration > 0:
                buff.last_tick_time += dt
                while buff.last_tick_time >= buff.tick_interval:
                    buff.last_tick_time -= buff.tick_interval
                    events.append({
                        "type": "tick",
                        "id": buff.id,
                        "name": buff.name,
                        "damage": self.calculate_dot(buff),
                    })
            # 堆叠衰减：每层独立计时，层到期则掉层
            if buff.stack_timers:
                buff.stack_timers = [t - dt for t in buff.stack_timers]
                alive = [t for t in buff.stack_timers if t > 0]
                decayed = len(buff.stack_timers) - len(alive)
                buff.stack_timers = alive
                if decayed > 0 and buff.duration > 0:
                    buff.stack_count = max(1, len(alive))
                    events.append({
                        "type": "stack_decay",
                        "id": buff.id,
                        "name": buff.name,
                        "stack_count": buff.stack_count,
                    })
            # 到期处理
            if buff.duration <= 0:
                expired.append(buff)
                events.append({"type": "expired", "id": buff.id, "name": buff.name})
        for buff in expired:
            if buff in self.buffs:
                self.buffs.remove(buff)
        return events

    def dispel_buff(self, buff_id: str, max_stacks: Optional[int] = None) -> bool:
        """驱散Buff：移除所有堆叠；不可驱散的Buff直接拒绝"""
        removed = False
        for buff in list(self.buffs):
            if buff.id != buff_id or not buff.is_dispellable:
                continue
            if max_stacks is None or max_stacks >= buff.stack_count:
                self.buffs.remove(buff)
            else:
                buff.stack_count -= max_stacks
                buff.stack_timers = buff.stack_timers[:buff.stack_count]
            removed = True
        return removed

    def dispel_all(self, count: int = 1) -> list[Buff]:
        """驱散最多count个可驱散Buff（数量限制），跳过不可驱散的"""
        dispelled: list[Buff] = []
        for buff in list(self.buffs):
            if len(dispelled) >= count:
                break
            if buff.is_dispellable:
                self.buffs.remove(buff)
                dispelled.append(buff)
        return dispelled

    def apply_effects(self) -> dict:
        """应用Buff效果：属性加成 + 状态效果（眩晕、沉默等）"""
        modified = dict(self.base_stats)
        for buff in self.get_active_buffs():
            for stat, value in buff.effects.items():
                if isinstance(value, bool) or stat not in modified:
                    # 状态效果，直接置位
                    modified[stat] = value
                else:
                    modified[stat] += value * buff.stack_count
        return modified

    def get_damage_multiplier(self) -> float:
        """伤害修正：汇总所有增伤/减伤Buff"""
        multiplier = 1.0
        for buff in self.get_active_buffs():
            multiplier += buff.damage_modifier * buff.stack_count
        return max(0.0, multiplier)

    def modify_damage(self, base_damage: float) -> float:
        """应用伤害修正后的实际伤害"""
        return base_damage * self.get_damage_multiplier()

    def on_attacked(self, incoming_damage: float) -> float:
        """被攻击时的触发效果：反伤"""
        reflected = 0.0
        for buff in self.get_active_buffs():
            if buff.reflect_ratio > 0:
                reflected += incoming_damage * buff.reflect_ratio * buff.stack_count
        return reflected

    def calculate_dot(self, buff: Buff, resistance: float = 0.0,
                      crit: Optional[bool] = None) -> float:
        """计算持续伤害：攻击力加成 + 抗性减免 + 暴击"""
        attack = self.base_stats.get("attack", 100)
        damage = buff.tick_damage * (attack / 100.0) * buff.stack_count
        damage *= max(0.0, 1.0 - resistance)
        if crit is None:
            crit = random.random() < buff.crit_chance
        if crit:
            damage *= buff.crit_multiplier
        return damage

    def get_buff_by_id(self, buff_id: str) -> Optional[Buff]:
        """根据ID获取Buff"""
        for buff in self.buffs:
            if buff.id == buff_id:
                return buff
        return None

    def remove_expired(self):
        """移除过期Buff"""
        self.buffs = [b for b in self.buffs if b.duration > 0]

    def get_active_buffs(self) -> list[Buff]:
        """获取所有活跃Buff"""
        return [b for b in self.buffs if b.duration > 0]
