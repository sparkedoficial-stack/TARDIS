#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TARDIS SOBERANO :: MOTOR MATEMÁTICO Y PARSER DE VOZ NATURAL
GODWORKS SYSTEM · Núcleo de Inferencia Cuántica y Traducción Fonética
"""

import re
import ast
import math
import operator as op

# Tablas léxicas para números en español
UNITS = {
    'cero': 0, 'un': 1, 'uno': 1, 'una': 1, 'dos': 2, 'tres': 3, 'cuatro': 4,
    'cinco': 5, 'seis': 6, 'siete': 7, 'ocho': 8, 'nueve': 9, 'diez': 10,
    'once': 11, 'doce': 12, 'trece': 13, 'catorce': 14, 'quince': 15,
    'dieciséis': 16, 'dieciseis': 16, 'diecisiete': 17, 'dieciocho': 18, 'diecinueve': 19,
    'veinte': 20, 'veintiuno': 21, 'veintiún': 21, 'veintiun': 21, 'veintiuna': 21,
    'veintidós': 22, 'veintidos': 22, 'veintitrés': 23, 'veintitres': 23,
    'veinticuatro': 24, 'veinticinco': 25, 'veintiséis': 26, 'veintiseis': 26,
    'veintisiete': 27, 'veintiocho': 28, 'veintinueve': 29,
    'treinta': 30, 'cuarenta': 40, 'cincuenta': 50, 'sesenta': 60,
    'setenta': 70, 'ochenta': 80, 'noventa': 90
}

HUNDREDS = {
    'cien': 100, 'ciento': 100,
    'doscientos': 200, 'doscientas': 200,
    'trescientos': 300, 'trescientas': 300,
    'cuatrocientos': 400, 'cuatrocientas': 400,
    'quinientos': 500, 'quinientas': 500,
    'seiscientos': 600, 'seiscientas': 600,
    'setecientos': 700, 'setecientas': 700,
    'ochocientos': 800, 'ochocientas': 800,
    'novecientos': 900, 'novecientas': 900
}

ALL_NUM_WORDS = set(list(UNITS.keys()) + list(HUNDREDS.keys()) + ['mil', 'millón', 'millon', 'millones', 'y'])

def convert_spanish_number_phrase(tokens):
    """Convierte una lista de tokens de números en español a un número entero o flotante."""
    total = 0
    current = 0
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in UNITS:
            current += UNITS[tok]
        elif tok in HUNDREDS:
            current += HUNDREDS[tok]
        elif tok == 'mil':
            if current == 0:
                current = 1
            total += current * 1000
            current = 0
        elif tok in ('millón', 'millon', 'millones'):
            if current == 0:
                current = 1
            total += current * 1000000
            current = 0
        elif tok == 'y':
            pass
        elif tok.isdigit():
            current += int(tok)
        i += 1
    return total + current

def parse_spoken_text_to_math(raw_text: str):
    """
    Traduce texto dictado en lenguaje natural (español) a una expresión matemática evaluable.
    Retorna una tupla: (expresion_matematica, comando_especial)
    """
    if not raw_text:
        return "", None

    text = raw_text.lower().strip()
    
    # Detección de comandos de control
    if any(cmd in text for cmd in ['limpiar', 'borrar todo', 'reiniciar', 'reset']):
        return "", "CLEAR"
    if any(cmd in text for cmd in ['borra', 'borrar', 'retroceso', 'deshacer']):
        return "", "BACKSPACE"
    if any(cmd in text for cmd in ['repite', 'repetir', 'di de nuevo']):
        return "", "REPEAT"

    # Eliminar muletillas y frases introductorias
    intro_patterns = [
        r'^(por favor|oye tardis|tardis|oye|calcula|calculame|calcula me|dime cuánto es|dime cuanto es|cuánto es|cuanto es|resultado de|cuál es el resultado de|dime la|dime el|saca la cuenta de|saca)\s*',
        r'\s*(por favor|tardis)$'
    ]
    for pat in intro_patterns:
        text = re.sub(pat, '', text).strip()

    # Normalizar palabras comunes
    text = text.replace('á', 'a').replace('é', 'e').replace('í', 'i').replace('ó', 'o').replace('ú', 'u')

    # Reemplazar frases compuestas primero
    text = text.replace('raiz cuadrada de', 'sqrt(')
    text = text.replace('raiz cuadrada', 'sqrt(')
    text = text.replace('raiz de', 'sqrt(')
    text = text.replace('al cuadrado', '** 2')
    text = text.replace('al cubo', '** 3')
    text = text.replace('elevado a la potencia', '**')
    text = text.replace('elevado a la', '**')
    text = text.replace('elevado al', '**')
    text = text.replace('elevado a', '**')
    text = text.replace('potencia de', '**')
    
    # Trigonometría
    text = text.replace('seno de', 'sin(')
    text = text.replace('coseno de', 'cos(')
    text = text.replace('tangente de', 'tan(')
    text = text.replace('logaritmo de', 'log(')
    text = text.replace('logaritmo natural de', 'ln(')

    # Fracciones y múltiplos comunes
    text = re.sub(r'la mitad de\s+([\w\d\s]+)', r'(\1 / 2)', text)
    text = re.sub(r'(el tercio de|la tercera parte de)\s+([\w\d\s]+)', r'(\1 / 3)', text)
    text = re.sub(r'(el doble de)\s+([\w\d\s]+)', r'(2 * \1)', text)
    text = re.sub(r'(el triple de)\s+([\w\d\s]+)', r'(3 * \1)', text)
    text = re.sub(r'(el cuadruple de)\s+([\w\d\s]+)', r'(4 * \1)', text)

    # Porcentaje compuesto: "X por ciento de Y" -> "(X / 100) * Y"
    pct_match = re.search(r'([\w\d\s]+)\s+por ciento de\s+([\w\d\s]+)', text)
    if pct_match:
        part_x = pct_match.group(1).strip()
        part_y = pct_match.group(2).strip()
        text = f"({part_x} / 100) * {part_y}"

    # Reemplazo de operadores
    text = text.replace('multiplicado por', ' * ')
    text = text.replace('multiplica por', ' * ')
    text = text.replace('dividido entre', ' / ')
    text = text.replace('dividido por', ' / ')
    text = text.replace('divide entre', ' / ')
    text = text.replace('partido por', ' / ')
    text = text.replace('partido entre', ' / ')
    text = text.replace('sobre', ' / ')
    text = text.replace('mas', ' + ')
    text = text.replace('menos', ' - ')
    text = text.replace('por', ' * ')
    text = text.replace('entre', ' / ')
    text = text.replace('x', ' * ')
    text = text.replace('abrir parentesis', ' ( ')
    text = text.replace('abre parentesis', ' ( ')
    text = text.replace('parentesis', ' ( ')
    text = text.replace('cerrar parentesis', ' ) ')
    text = text.replace('cierra parentesis', ' ) ')
    text = text.replace('punto', '.')
    text = text.replace('coma', '.')

    # Constantes
    text = re.sub(r'\bpi\b', str(math.pi), text)
    text = re.sub(r'\beuler\b', str(math.e), text)

    # Agrupar tokens de palabras numéricas a dígitos
    raw_tokens = text.split()
    processed_tokens = []
    num_buffer = []

    for tok in raw_tokens:
        clean_tok = tok.strip(".,;:!?")
        if clean_tok in ALL_NUM_WORDS or clean_tok.isdigit():
            num_buffer.append(clean_tok)
        else:
            if num_buffer:
                num_val = convert_spanish_number_phrase(num_buffer)
                processed_tokens.append(str(num_val))
                num_buffer = []
            processed_tokens.append(tok)

    if num_buffer:
        num_val = convert_spanish_number_phrase(num_buffer)
        processed_tokens.append(str(num_val))

    expr = " ".join(processed_tokens)

    # Compactar decimales separados (ej: "5 . 5" -> "5.5")
    expr = re.sub(r'(\d+)\s*[\.,]\s*(\d+)', r'\1.\2', expr)
    expr = re.sub(r'(sqrt|sin|cos|tan|log|ln)\s*\(\s*', r'\1(', expr)

    # Balancear paréntesis si quedaron abiertos (ej: sqrt(144 -> sqrt(144))
    open_parens = expr.count('(')
    close_parens = expr.count(')')
    if open_parens > close_parens:
        expr += ')' * (open_parens - close_parens)

    # Limpiar espacios repetidos
    expr = re.sub(r'\s+', ' ', expr).strip()
    return expr, "CALCULATE"


# Evaluador AST Seguro
SAFE_OPS = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
    ast.FloorDiv: op.floordiv,
    ast.Mod: op.mod,
    ast.Pow: op.pow,
    ast.USub: op.neg,
    ast.UAdd: op.pos,
}

def create_safe_funcs(angle_mode="DEG"):
    if angle_mode == "DEG":
        return {
            'sqrt': math.sqrt,
            'sin': lambda x: math.sin(math.radians(x)),
            'cos': lambda x: math.cos(math.radians(x)),
            'tan': lambda x: math.tan(math.radians(x)),
            'asin': lambda x: math.degrees(math.asin(x)),
            'acos': lambda x: math.degrees(math.acos(x)),
            'atan': lambda x: math.degrees(math.atan(x)),
            'log': math.log10,
            'ln': math.log,
            'abs': abs,
            'round': round,
            'factorial': math.factorial,
        }
    else:
        return {
            'sqrt': math.sqrt,
            'sin': math.sin,
            'cos': math.cos,
            'tan': math.tan,
            'asin': math.asin,
            'acos': math.acos,
            'atan': math.atan,
            'log': math.log10,
            'ln': math.log,
            'abs': abs,
            'round': round,
            'factorial': math.factorial,
        }

SAFE_CONSTS = {
    'pi': math.pi,
    'e': math.e,
}

def _eval_ast_node(node, safe_funcs):
    if isinstance(node, ast.Expression):
        return _eval_ast_node(node.body, safe_funcs)
    elif isinstance(node, ast.Constant):
        return node.value
    elif isinstance(node, ast.BinOp):
        left = _eval_ast_node(node.left, safe_funcs)
        right = _eval_ast_node(node.right, safe_funcs)
        op_func = SAFE_OPS.get(type(node.op))
        if op_func is None:
            raise ValueError(f"Operador no soportado: {type(node.op).__name__}")
        return op_func(left, right)
    elif isinstance(node, ast.UnaryOp):
        operand = _eval_ast_node(node.operand, safe_funcs)
        op_func = SAFE_OPS.get(type(node.op))
        if op_func is None:
            raise ValueError(f"Operador unario no soportado: {type(node.op).__name__}")
        return op_func(operand)
    elif isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValueError("Llamada no autorizada")
        func_name = node.func.id
        if func_name not in safe_funcs:
            raise ValueError(f"Función desconocida: {func_name}")
        args = [_eval_ast_node(arg, safe_funcs) for arg in node.args]
        return safe_funcs[func_name](*args)
    elif isinstance(node, ast.Name):
        if node.id in SAFE_CONSTS:
            return SAFE_CONSTS[node.id]
        raise ValueError(f"Símbolo no identificado: {node.id}")
    else:
        raise ValueError("Expresión no válida")

def evaluate_expression(expr_str: str, angle_mode="DEG"):
    """Evalúa de forma segura una expresión matemática string y devuelve el resultado formateado."""
    clean_expr = expr_str.strip()
    if not clean_expr:
        return 0, ""

    # Normalizaciones matemáticas
    clean_expr = clean_expr.replace('^', '**')
    clean_expr = clean_expr.replace('×', '*').replace('÷', '/')
    
    # Tratamiento de porcentajes sueltos como "50%" -> "(50/100)"
    clean_expr = re.sub(r'(\d+(\.\d+)?)%', r'(\1/100)', clean_expr)

    safe_funcs = create_safe_funcs(angle_mode)
    tree = ast.parse(clean_expr, mode='eval')
    res = _eval_ast_node(tree, safe_funcs)

    # Redondear números flotantes muy cercanos a enteros
    if isinstance(res, float):
        if math.isclose(res, round(res), abs_tol=1e-11):
            res = round(res)
        else:
            res = round(res, 8)

    return res, clean_expr
