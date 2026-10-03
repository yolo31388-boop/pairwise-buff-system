"""状态效果Buff系统 - 存在bug"""
from dataclasses import dataclass, field
from typing import Optional, Callable


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


class BuffSystem:
    def __init__(self):
        self.buffs: list[Buff] = []
        self.base_stats: dict = {"attack": 100, "defense": 50, "speed": 10}
        self.current_time: float = 0.0

    def apply_buff(self, buff: Buff) -> bool:
        """添加Buff - BUG: 不检查是否已有相同Buff"""
        # BUG: 不检查相同Buff，直接添加
        self.buffs.append(buff)
        return True

    def update_buffs(self, dt: float) -> list[dict]:
        """更新Buff - BUG: 只扣持续时间不做周期效果"""
        self.current_time += dt
        expired = []
        for buff in self.buffs:
            buff.duration -= dt
            # BUG: 不做周期效果（tick）
            if buff.duration <= 0:
                expired.append(buff)
        # BUG: 不做到期处理，Buff到期了不移除
        return [{"id": b.id, "name": b.name} for b in expired]

    def dispel_buff(self, buff_id: str) -> bool:
        """驱散Buff - BUG: 只驱散第一层"""
        for i, buff in enumerate(self.buffs):
            if buff.id == buff_id and buff.is_dispellable:
                # BUG: 只驱散一个，不驱散所有相同ID的
                self.buffs.pop(i)
                return True
        return False

    def apply_effects(self) -> dict:
        """应用Buff效果 - BUG: 只做属性加成不做状态效果"""
        # BUG: 只做属性加成，不做状态效果（眩晕、沉默等）
        modified = dict(self.base_stats)
        for buff in self.buffs:
            for stat, value in buff.effects.items():
                if stat in modified:
                    modified[stat] += value * buff.stack_count
        return modified

    def calculate_dot(self, buff: Buff) -> float:
        """计算持续伤害 - BUG: 只做固定伤害"""
        # BUG: 不做攻击力加成，不做抗性
        return buff.tick_damage

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
