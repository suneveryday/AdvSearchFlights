from __future__ import annotations

AIRPORT_NAME_ZH = {
    "SHA": "上海虹桥国际机场",
    "PVG": "上海浦东国际机场",
    "PEK": "北京首都国际机场",
    "PKX": "北京大兴国际机场",
    "CAN": "广州白云国际机场",
    "SZX": "深圳宝安国际机场",
    "CTU": "成都双流国际机场",
    "TFU": "成都天府国际机场",
    "HKG": "香港国际机场",
    "TPE": "台北桃园国际机场",
    "SIN": "新加坡樟宜机场",
    "KUL": "吉隆坡国际机场",
    "MEL": "墨尔本机场",
    "SYD": "悉尼金斯福德·史密斯机场",
    "BNE": "布里斯班机场",
    "PER": "珀斯机场",
    "AKL": "奥克兰机场",
    "MNL": "马尼拉尼诺伊·阿基诺国际机场",
    "BKK": "曼谷素万那普国际机场",
    "DMK": "曼谷廊曼国际机场",
    "HND": "东京羽田机场",
    "NRT": "东京成田国际机场",
    "FSZ": "富士山静冈机场",
    "KIX": "大阪关西国际机场",
    "ITM": "大阪伊丹机场",
    "UKB": "神户机场",
    "GMP": "首尔金浦国际机场",
    "ICN": "首尔仁川国际机场",
    "JFK": "纽约肯尼迪国际机场",
    "EWR": "纽约纽瓦克自由国际机场",
    "LGA": "纽约拉瓜迪亚机场",
    "LAX": "洛杉矶国际机场",
    "SFO": "旧金山国际机场",
}

CITY_AIRPORTS = {
    "上海": ["PVG", "SHA"],
    "北京": ["PEK", "PKX"],
    "成都": ["CTU", "TFU"],
    "墨尔本": ["MEL"],
    "悉尼": ["SYD"],
    "东京": ["HND", "NRT"],
    "静冈": ["FSZ"],
    "大阪": ["KIX", "ITM", "UKB"],
    "曼谷": ["BKK", "DMK"],
    "纽约": ["JFK", "EWR", "LGA"],
    "BJS": ["PEK", "PKX"],
    "NYC": ["JFK", "EWR", "LGA"],
    "TYO": ["HND", "NRT"],
    "OSA": ["KIX", "ITM", "UKB"],
}

CITY_TO_IATA = {
    "上海": "SHA",
    "北京": "BJS",
    "广州": "CAN",
    "深圳": "SZX",
    "成都": "CTU",
    "香港": "HKG",
    "新加坡": "SIN",
    "吉隆坡": "KUL",
    "墨尔本": "MEL",
    "悉尼": "SYD",
    "布里斯班": "BNE",
    "东京": "TYO",
    "静冈": "FSZ",
    "大阪": "OSA",
    "曼谷": "BKK",
    "纽约": "NYC",
    "洛杉矶": "LAX",
    "旧金山": "SFO",
}

AIRLINE_NAME_ZH = {
    "MU": "中国东方航空",
    "CA": "中国国际航空",
    "CZ": "中国南方航空",
    "CX": "国泰航空",
    "HX": "香港航空",
    "HO": "吉祥航空",
    "SQ": "新加坡航空",
    "QF": "澳洲航空",
    "JQ": "捷星航空",
    "TG": "泰国航空",
    "MH": "马来西亚航空",
    "D7": "亚洲航空长途",
    "OD": "马印航空",
    "CI": "中华航空",
    "5J": "宿务太平洋航空",
    "PR": "菲律宾航空",
    "NH": "全日空",
    "JL": "日本航空",
    "OZ": "韩亚航空",
    "KE": "大韩航空",
    "AA": "美国航空",
    "DL": "达美航空",
    "UA": "美国联合航空",
}

AIRCRAFT_NAME_ZH = {
    "320": "空客 A320",
    "321": "空客 A321",
    "32N": "空客 A320neo",
    "333": "空客 A330-300",
    "339": "空客 A330-900neo",
    "359": "空客 A350-900",
    "388": "空客 A380-800",
    "738": "波音 737-800",
    "7M8": "波音 737 MAX 8",
    "77W": "波音 777-300ER",
    "789": "波音 787-9",
}

for _code, _name in AIRPORT_NAME_ZH.items():
    CITY_TO_IATA.setdefault(_name, _code)


def airport_name_zh(code: str | None) -> str | None:
    if not code:
        return None
    return AIRPORT_NAME_ZH.get(code.upper())


def airline_name_zh(code_or_name: str | None) -> str | None:
    if not code_or_name:
        return None
    code = code_or_name.strip().upper()[:2]
    return AIRLINE_NAME_ZH.get(code)


def aircraft_name_zh(code: str | None) -> str | None:
    if not code:
        return None
    normalized = code.strip()
    return AIRCRAFT_NAME_ZH.get(normalized.upper()) or aircraft_text_zh(normalized)


def aircraft_text_zh(value: str | None) -> str | None:
    if not value:
        return None
    translated = value.strip()
    for source, target in {
        "Airbus": "空客",
        "Boeing": "波音",
        "Embraer": "巴航工业",
        "Passenger": "客机",
        "(Sharklets)": "",
    }.items():
        translated = translated.replace(source, target)
    return " ".join(translated.split())


def airport_label(code: str, name_zh: str | None = None) -> str:
    return f"{code}({name_zh})" if name_zh else code


def layover_hours(minutes: int) -> float:
    return round(minutes / 60, 1)
