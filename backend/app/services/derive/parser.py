"""标签计算表达式解析器。

支持的业务语法（全部中文，业务人员可手写）：

    规则("FILT-0001") 与 近30天消费金额 大于 1000
    (城市 等于 "上海" 或 城市 等于 "杭州") 与 最近联系日期 不为空
    等级 等于 "A"
    是否企业客户 等于 是

运算符：等于、不等于、大于、大于等于、小于、小于等于、包含、不包含、为空、不为空
逻辑：与、或；括号改变结合顺序；规则("规则编号") 引用数据筛选里的生效条件。

解析结果是纯字典组成的 AST，求值器在 app.services.derive.engine 里执行。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# 长度从长到短，保证「不等于」优先于「等于」、「不为空」优先于「为空」
OPERATORS = ["不等于", "大于等于", "小于等于", "不包含", "大于", "小于", "等于", "包含", "不为空", "为空"]
UNARY_OPS = {"为空", "不为空"}
RULE_FN = "规则"
AND_WORDS = {"与", "AND", "and"}
OR_WORDS = {"或", "OR", "or"}


class ExpressionError(ValueError):
    """表达式语法不合法时抛出，消息要能直接给业务人员看。"""


@dataclass
class Token:
    kind: str  # lparen | rparen | and | or | field | op | value | rule
    text: str
    pos: int
    value: Any = None


def _is_word_char(ch: str) -> bool:
    return ch not in "() \t\r\n\"'" and not ch.isspace()


def tokenize(expr: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    n = len(expr)
    while i < n:
        ch = expr[i]
        if ch.isspace():
            i += 1
            continue
        if ch == "(":
            tokens.append(Token("lparen", ch, i))
            i += 1
            continue
        if ch == ")":
            tokens.append(Token("rparen", ch, i))
            i += 1
            continue
        if ch in "\"'":
            quote = ch
            j = i + 1
            buf: list[str] = []
            while j < n and expr[j] != quote:
                buf.append(expr[j])
                j += 1
            if j >= n:
                raise ExpressionError(f"第 {i + 1} 列起的字符串缺少结束引号 {quote}")
            tokens.append(Token("value", "".join(buf), i, "".join(buf)))
            i = j + 1
            continue

        start = i
        while i < n and _is_word_char(expr[i]):
            i += 1
        run = expr[start:i]

        # 规则("FILT-0001")：函数名可能和左括号之间没有空格，先剥出函数名
        if run.startswith(RULE_FN):
            rest = run[len(RULE_FN):]
            tokens.append(Token("rule", RULE_FN, start))
            if rest:
                _emit_word(tokens, rest, start + len(RULE_FN))
            continue
        _emit_word(tokens, run, start)
    return tokens


def _emit_word(tokens: list[Token], run: str, base: int) -> None:
    """把一段无空格文本切成 字段/运算符/值/逻辑词，运算符可能夹在中间。"""
    # 先找最早出现的运算符（同位置取更长的关键字）
    hit_pos, hit_op = None, None
    for op in OPERATORS:
        pos = run.find(op)
        if pos >= 0 and (hit_pos is None or pos < hit_pos or (pos == hit_pos and len(op) > len(hit_op or ""))):
            hit_pos, hit_op = pos, op
    if hit_pos is None:
        _emit_plain(tokens, run, base)
        return
    left = run[:hit_pos]
    if left:
        _emit_plain(tokens, left, base)
    tokens.append(Token("op", hit_op, base + hit_pos))
    right = run[hit_pos + len(hit_op):]
    if right:
        if hit_op in UNARY_OPS:
            raise ExpressionError(f"运算符「{hit_op}」不需要比较值，请去掉后面的「{right}」")
        tokens.append(Token("value", right, base + hit_pos + len(hit_op), _parse_literal(right)))


def _emit_plain(tokens: list[Token], text: str, base: int) -> None:
    if text in AND_WORDS:
        tokens.append(Token("and", text, base))
    elif text in OR_WORDS:
        tokens.append(Token("or", text, base))
    else:
        tokens.append(Token("field", text, base))


def _parse_literal(text: str) -> Any:
    if text in ("是", "真", "true", "True"):
        return True
    if text in ("否", "假", "false", "False"):
        return False
    try:
        if "." in text:
            return float(text)
        return int(text)
    except ValueError:
        return text  # 日期、枚举值等按字符串处理


class Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.idx = 0

    def peek(self) -> Token | None:
        return self.tokens[self.idx] if self.idx < len(self.tokens) else None

    def next(self) -> Token:
        tok = self.tokens[self.idx]
        self.idx += 1
        return tok

    def parse(self) -> dict[str, Any]:
        if not self.tokens:
            raise ExpressionError("计算表达式为空，请先填写字段与比较条件")
        node = self.parse_or()
        if self.peek() is not None:
            tok = self.peek()
            raise ExpressionError(f"第 {tok.pos + 1} 列附近的「{tok.text}」无法并入表达式，请检查括号与逻辑词")
        return node

    def parse_or(self) -> dict[str, Any]:
        children = [self.parse_and()]
        while self.peek() and self.peek().kind == "or":
            self.next()
            children.append(self.parse_and())
        return children[0] if len(children) == 1 else {"type": "logic", "op": "或", "children": children}

    def parse_and(self) -> dict[str, Any]:
        children = [self.parse_unary()]
        while self.peek() and self.peek().kind == "and":
            self.next()
            children.append(self.parse_unary())
        return children[0] if len(children) == 1 else {"type": "logic", "op": "与", "children": children}

    def parse_unary(self) -> dict[str, Any]:
        tok = self.peek()
        if tok is None:
            raise ExpressionError("表达式在逻辑词后提前结束，缺少后续条件")
        if tok.kind == "lparen":
            self.next()
            node = self.parse_or()
            closing = self.peek()
            if closing is None or closing.kind != "rparen":
                raise ExpressionError(f"第 {tok.pos + 1} 列的左括号缺少匹配的右括号")
            self.next()
            return node
        if tok.kind == "rule":
            return self.parse_rule()
        return self.parse_compare()

    def parse_rule(self) -> dict[str, Any]:
        rule_tok = self.next()
        lp = self.peek()
        if lp is None or lp.kind != "lparen":
            raise ExpressionError(f"第 {rule_tok.pos + 1} 列的「规则」后面应为 (规则编号)")
        self.next()
        code_tok = self.peek()
        if code_tok is None or code_tok.kind != "value":
            raise ExpressionError("规则引用应写成 规则(\"FILT-0001\")，括号内是规则编号字符串")
        self.next()
        rp = self.peek()
        if rp is None or rp.kind != "rparen":
            raise ExpressionError(f"规则「{code_tok.text}」后面缺少右括号")
        self.next()
        return {"type": "rule", "code": code_tok.text}

    def parse_compare(self) -> dict[str, Any]:
        field_tok = self.peek()
        if field_tok is None or field_tok.kind != "field":
            raise ExpressionError(f"第 {(field_tok.pos + 1) if field_tok else 0} 列附近应以字段名开头")
        self.next()
        op_tok = self.peek()
        if op_tok is None or op_tok.kind != "op":
            raise ExpressionError(f"字段「{field_tok.text}」后面缺少比较运算符（等于/大于/包含/为空 等）")
        self.next()
        if op_tok.text in UNARY_OPS:
            return {"type": "compare", "field": field_tok.text, "op": op_tok.text, "value": None}
        val_tok = self.peek()
        # 允许不写引号的字面量（数字、日期、枚举），分词器会先标成 field，这里按值接收
        if val_tok is None or val_tok.kind not in ("value", "field"):
            raise ExpressionError(f"运算符「{op_tok.text}」后面缺少比较值")
        self.next()
        value = val_tok.value if val_tok.kind == "value" else _parse_literal(val_tok.text)
        return {"type": "compare", "field": field_tok.text, "op": op_tok.text, "value": value}


def parse_expression(expr: str) -> dict[str, Any]:
    """表达式字符串 → AST；语法错误统一抛 ExpressionError。"""
    return Parser(tokenize(expr or "")).parse()
