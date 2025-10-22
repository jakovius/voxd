ISO_639_1: dict[str, str] = {
    "aa": "Afar", "ab": "Abkhazian", "ae": "Avestan", "af": "Afrikaans", "ak": "Akan",
    "am": "Amharic", "an": "Aragonese", "ar": "Arabic", "as": "Assamese", "av": "Avaric",
    "ay": "Aymara", "az": "Azerbaijani", "ba": "Bashkir", "be": "Belarusian", "bg": "Bulgarian",
    "bh": "Bihari languages", "bi": "Bislama", "bm": "Bambara", "bn": "Bengali", "bo": "Tibetan",
    "br": "Breton", "bs": "Bosnian", "ca": "Catalan; Valencian", "ce": "Chechen", "ch": "Chamorro",
    "co": "Corsican", "cr": "Cree", "cs": "Czech", "cu": "Church Slavic", "cv": "Chuvash",
    "cy": "Welsh", "da": "Danish", "de": "German", "dv": "Divehi; Dhivehi; Maldivian", "dz": "Dzongkha",
    "ee": "Ewe", "el": "Greek", "en": "English", "eo": "Esperanto", "es": "Spanish; Castilian",
    "et": "Estonian", "eu": "Basque", "fa": "Persian", "ff": "Fulah", "fi": "Finnish",
    "fj": "Fijian", "fo": "Faroese", "fr": "French", "fy": "Western Frisian", "ga": "Irish",
    "gd": "Scottish Gaelic; Gaelic", "gl": "Galician", "gn": "Guaraní", "gu": "Gujarati", "gv": "Manx",
    "ha": "Hausa", "he": "Hebrew", "hi": "Hindi", "ho": "Hiri Motu", "hr": "Croatian",
    "ht": "Haitian; Haitian Creole", "hu": "Hungarian", "hy": "Armenian", "hz": "Herero",
    "ia": "Interlingua", "id": "Indonesian", "ie": "Interlingue", "ig": "Igbo", "ii": "Sichuan Yi; Nuosu",
    "ik": "Inupiaq", "io": "Ido", "is": "Icelandic", "it": "Italian", "iu": "Inuktitut",
    "ja": "Japanese", "jv": "Javanese", "ka": "Georgian", "kg": "Kongo", "ki": "Kikuyu; Gikuyu",
    "kj": "Kuanyama; Kwanyama", "kk": "Kazakh", "kl": "Kalaallisut; Greenlandic", "km": "Central Khmer",
    "kn": "Kannada", "ko": "Korean", "kr": "Kanuri", "ks": "Kashmiri", "ku": "Kurdish", "kv": "Komi",
    "kw": "Cornish", "ky": "Kirghiz; Kyrgyz", "la": "Latin", "lb": "Luxembourgish; Letzeburgesch",
    "lg": "Ganda", "li": "Limburgish; Limburger; Limburgan", "ln": "Lingala", "lo": "Lao",
    "lt": "Lithuanian", "lu": "Luba-Katanga", "lv": "Latvian", "mg": "Malagasy", "mh": "Marshallese",
    "mi": "Māori", "mk": "Macedonian", "ml": "Malayalam", "mn": "Mongolian", "mr": "Marathi",
    "ms": "Malay", "mt": "Maltese", "my": "Burmese", "na": "Nauru", "nb": "Norwegian Bokmål",
    "nd": "North Ndebele", "ne": "Nepali", "ng": "Ndonga", "nl": "Dutch; Flemish", "nn": "Norwegian Nynorsk",
    "no": "Norwegian", "nr": "South Ndebele", "nv": "Navajo; Navaho", "ny": "Chichewa; Chewa; Nyanja",
    "oc": "Occitan", "oj": "Ojibwa", "om": "Oromo", "or": "Oriya", "os": "Ossetian; Ossetic",
    "pa": "Panjabi; Punjabi", "pi": "Pali", "pl": "Polish", "ps": "Pashto; Pushto", "pt": "Portuguese",
    "qu": "Quechua", "rm": "Romansh", "rn": "Rundi", "ro": "Romanian; Moldavian; Moldovan",
    "ru": "Russian", "rw": "Kinyarwanda", "sa": "Sanskrit", "sc": "Sardinian", "sd": "Sindhi",
    "se": "Northern Sami", "sg": "Sango", "si": "Sinhala; Sinhalese", "sk": "Slovak", "sl": "Slovenian",
    "sm": "Samoan", "sn": "Shona", "so": "Somali", "sq": "Albanian", "sr": "Serbian",
    "ss": "Swati", "st": "Southern Sotho", "su": "Sundanese", "sv": "Swedish", "sw": "Swahili",
    "ta": "Tamil", "te": "Telugu", "tg": "Tajik", "th": "Thai", "ti": "Tigrinya", "tk": "Turkmen",
    "tl": "Tagalog", "tn": "Tswana", "to": "Tonga (Tonga Islands)", "tr": "Turkish", "ts": "Tsonga",
    "tt": "Tatar", "tw": "Twi", "ty": "Tahitian", "ug": "Uighur; Uyghur", "uk": "Ukrainian",
    "ur": "Urdu", "uz": "Uzbek", "ve": "Venda", "vi": "Vietnamese", "vo": "Volapük",
    "wa": "Walloon", "wo": "Wolof", "xh": "Xhosa", "yi": "Yiddish", "yo": "Yoruba",
    "za": "Zhuang; Chuang", "zh": "Chinese", "zu": "Zulu",
}

def normalize_lang_code(s: str) -> str:
    return (s or "").strip().lower()

def is_valid_lang(code: str) -> bool:
    c = normalize_lang_code(code)
    return c == "auto" or c in ISO_639_1

def code_to_name(code: str) -> str:
    c = normalize_lang_code(code)
    if c == "auto":
        return "Auto (detect)"
    return ISO_639_1.get(c, c)

def search_languages(query: str) -> list[tuple[str, str]]:
    q = (query or "").strip().lower()
    items = list(ISO_639_1.items())
    if not q:
        return sorted(items, key=lambda kv: kv[1])
    return sorted([kv for kv in items if q in kv[0] or q in kv[1].lower()], key=lambda kv: kv[1])


