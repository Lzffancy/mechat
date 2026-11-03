# -*- coding: utf-8 -*-
"""微信群聊分析。

把「导出 → 统计 → 主题 → 关系 → 报告」里能写死的部分固定成代码，
把必须靠判断的部分交给 LLM，提示词在 `prompts/`。

    from wxchat_analysis import schema, report

    g = schema.load("群.jsonl", members="群_members.csv")
    data = report.build_report(g)
    report.write(data, "out/")
"""
from .schema import Group, Message, load, load_jsonl, load_readable_txt

__all__ = ["Group", "Message", "load", "load_jsonl", "load_readable_txt"]
__version__ = "0.1.0"
