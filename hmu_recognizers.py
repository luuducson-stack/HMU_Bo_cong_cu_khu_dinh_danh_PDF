import base64
import pathlib
import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import List, Dict, Tuple, Iterable, Optional

@dataclass
class Finding:
    entity_type: str
    start: int
    end: int
    score: float
    text: str
    rule: str
    review_status: str = "PENDING_REVIEW"
    role: str = "UNKNOWN"

# HMU Presidio Vietnamese PII Recognizer v2.0
# Strategy:
# (1) strict & OCR-tolerant labelled anchors;
# (2) preserve PATIENT_ID, MEDICAL_RECORD_ID, Hospital Name, Gender for post-inspection & research;
# (3) redact Patient/Relative Name, DOB/YOB, Phone, Address, National/Insurance IDs, Doctor/Staff Names & Watermarks.

DATE = r"(?:0?[1-9]|[12]\d|3[01])[\/\-.](?:0?[1-9]|1[0-2])[\/\-.](?:19|20)\d{2}"
DOB_LABEL = r"(?:sinh\s*ng[aàåä]y|ng[aàåä]y\s*(?:,?\s*th[aáåä]ng\s*,?\s*(?:n[aăåä]m\s*)?)?sinh)"
YEAR = r"(?:19|20)\d{2}"
PHONE = r"(?:\+?84|0)(?:[ .\-]?\d){8,10}"
CCCD = r"\d{9,12}"
BH = r"[A-Z]{2}(?:[ \t\r\n\xa0\-]*[0-9]){11,14}(?![0-9])"
IDNUM = r"\d{6,14}"
INSURANCE_CARD_LABEL = r'(?:s[oố6]|m[aãäå])\s*th[eéẻ]\s*BH[YV]T'

WATERMARK_RE = re.compile(r"(?m)^[ \t\xa0]*([A-ZÀ-ỸĐa-zà-ỹđ]+(?:[ \t]+[A-ZÀ-ỸĐa-zà-ỹđ]+){1,5})_\d{8,16}[ \t\xa0]*$")

NAME_TOKEN = r"[^\W\d_]+(?:[-'.\"][^\W\d_]+)?"
PERSON_NAME = rf"{NAME_TOKEN}(?:[ \t]+{NAME_TOKEN}){{1,6}}"
NAME_STOP = r"(?=\s+(?:tuổi|tudi|tubi|năm\s*sinh|nam/nữ|giới\s*tính|gibi\s*tinh|địa\s*chỉ|diachi|khoa(?:/phòng)?|mã\s*(?:bn|bệnh\s*nhân|người\s*bệnh|hồ\s*sơ)|ngày\s*sinh|sinh\s*ngày|điện\s*thoại|số\s*thẻ\s*bhyt|chẩn\s*đoán)\s*:|\s+ngày\s+in\s*:|\n|$)"

# Note: PATIENT_ID and MEDICAL_RECORD_ID are intentionally preserved in v2.0 for post-inspection (hậu kiểm).
RULES: List[Tuple[str, str, str, float, int]] = [
    ('HEALTH_INSURANCE_ID','insurance_missing_prefix_ocr',rf'(?i)\b{INSURANCE_CARD_LABEL}[ \t]*[:：][ \t]*((?:[A-Z][ \t]*)?(?:\d[ \t]*){{11,14}})(?![ \t]*\d)',.99,1),
    ("DATE_OF_BIRTH", "dob_inline_label", rf"(?i)\b{DOB_LABEL}\s*[:：;]\s*({DATE})", 0.99, 1),
    ("PATIENT_AGE", "patient_age_postfix", r"(?i)(?<![\d.,])(\d{1,3})[ \t]*tu[oôơöổbdu]{1,2}i\b", 0.99, 1),
    ("PATIENT_AGE", "patient_age_anchor", r"(?i)\b(?:tu[oôơöổbdu]{1,2}i|tubi|tudi)[ \t]*(?:[:：]\s*|[ \t]*)(\d(?:[ \t|]*\d(?![.)]\s*[^\W\d_])){0,2})(?!\d)", 0.99, 1),
    ("HEALTH_INSURANCE_ID", "bhyt_anchor", rf"(?i)(?:s[oố6]\s*th[eéẻ]\s*|th[eéẻ]\s*)?BH[YV]T\s*[:\-]?\s*({BH})", 0.99, 1),
    ("NATIONAL_ID", "national_id_anchor", rf"(?i)(?:CCCD|CMND|số\s*CMTND(?:/số\s*hộ\s*chiếu/Căn\s*cước)?|Căn\s*cước|số\s*định\s*danh(?:\s*cá\s*nhân)?|hộ\s*chiếu)(?:\s*của\s*người\s*bệnh)?\s*[:\-]?\s*({CCCD})", 0.99, 1),
    ("YEAR_OF_BIRTH", "yob_anchor", rf"(?i)(?:n[aăäå]m[ \t]*sinh|\bNS)\s*[:\-]?\s*({YEAR})", 0.96, 1),
    ("PHONE_NUMBER_VN", "patient_phone_anchor", rf"(?i)(?:điện\s*thoại\s*(?:người\s*bệnh|người\s*nhà|số|cá\s*nhân)|số\s*điện\s*thoại(?:\s*(?:người\s*bệnh|người\s*nhà))?|số\s*ĐT|[dđ]i[eêéèệ]n\s*(?:(?:th|[aåä])o[aạäå]i)?(?:\s*s[oố60])?)\s*[:\-]?\s*({PHONE})", 0.99, 1),
    ("PHONE_NUMBER_VN", "phone_field_anchor", rf"(?im)^\s*(?:điện\s*thoại|số\s*điện\s*thoại|sđt|điện\s*thoại\s*số|[dđ]i[eêéèệ]n\s*(?:th|[aåä])o[aạäå]i(?:\s*s[oố60])?)\s*[:\-]?\s*({PHONE})\s*$", 0.96, 1),
    ("ADDRESS_VN", "sub_address_anchor", r"(?im)(?:xã\s*,?\s*phường|x[aãäå]\s*,?\s*ph[uưü][oờö]ng|thôn\s*,?\s*phố|th[oôö]n\s*,?\s*ph[oố6]|số\s*nhà(?:/thôn,\s*phố)?|tỉnh\s*,?\s*thành\s*phố|tinh\s*[.,\-]?\s*(?:th[aàäåf]nh\s*)?ph[oố6]|huyện\s*\(q\s*,\s*tx\))\s*[:.\-]*[ \t\xa0]*([^\n:]{2,100})", 0.97, 1),
    ("RELATIVE_NAME", "relative_inline_anchor", r"(?im)(?:(?:11|[I1]{1,2})\s*[.,\-]?\s*)?(?:h[oọ]\s*t[eê]n|ho\s*ten)\s*,?\s*(?:[dđ][iị]a\s*ch[iỉ]|dia\s*chi)?\s*ng[uưtrời&a-zA-ZÀ-ỹ]+\s*nh[aàåä](?:\s*khi\s*c[aầåä]n\s*b[aáåäio]+\s*tin)?\s*[:.\-]*[ \t\xa0]*([^\n]+)", 0.99, 1),
    ("HEALTHCARE_STAFF_NAME", "signer_inline_anchor", r"(?im)(?:k[yý]\s*s[oố]\s*b[oở]i|ng[uư][oờ]i\s*k[iíyý])\s*[:\-][ \t\xa0]*([^\n,;:]+)", 0.99, 1),
]

NAME_BAD_WORDS = {
    "khám bệnh", "làm bệnh án", "chỉ định", "điều trị", "chuyên khoa", "xét nghiệm",
    "giới tính", "địa chỉ", "số thẻ bhyt", "bệnh phẩm", "khoa hô hấp", "bệnh viện",
    "trường đại học", "người bệnh", "họ tên", "chẩn đoán", "kết quả xét nghiệm",
    "nội khoa", "ngoại khoa", "ung bướu", "da liễu", "cấp cứu", "hành chính",
    "tổng kết bệnh án", "bệnh án", "trưởng khoa", "giám đốc bệnh viện", "phòng kế hoạch tổng hợp",
    "thực hiện", "thuc hien", "kỹ thuật viên", "ky thuat vien",
    "chụp xquang", "chup xquang", "x-quang", "xquang", "chụp x-quang ngực thẳng",
    "ngực thẳng", "nguc thang", "nuôi cấy", "nuoi cay", "lo lắng", "lo lang", "dễ qua", "de qua",
    "uống", "uong", "chuyển viện", "chuyen vien", "hiện tại", "hien tai", "khám latex", "kham latex",
    "vi sinh", "kháng sinh đồ", "khang sinh do", "hồi hộp", "bồn chồn", "cơn đau"
}
ADDRESS_BAD_PREFIXES = (
    "phiếu ", "bệnh phẩm", "chẩn đoán", "xét nghiệm", "họ tên", "giới tính", "số thẻ",
    "mã hồ sơ", "mã bệnh", "bác sĩ", "bác sỹ", "huyện (q", "tỉnh, thành phố"
)

ICD_RE = re.compile(r"(?i)\b[A-Z]\s*\d{2}(?:\s*[.]\s*\d{1,2})?\b")
LAB_RE = re.compile(r"(?i)\b(?:pH|pCO2|pO2|HCO3|FiO2|SO2|MetHb|Hb|WBC|RBC|PLT|CRP|ALT|AST|GGT|Na|K|Cl|Creatinin|Glucose)\b")
MEASURE_RE = re.compile(r"(?i)\b\d+(?:[.,]\d+)?\s*(?:mg|g|ml|mmol/L|µmol/L|umol/L|mmHg|cm|mm|kg|°C|%)\b")
LIS_RE = re.compile(r"(?i)\bLIS\s*:\s*\d+\b")
SAMPLE_RE = re.compile(r"(?i)\b(?:mã\s*số\s*bệnh\s*phẩm|mã\s*số\s*mẫu)\s*:\s*[A-Z0-9\-]+")
ROOM_BED_RE = re.compile(r"(?i)\b(?:phòng|giường|buồng)\s*[:\-]?\s*[A-Z]?\d+[A-Z]?\b")
CLINICAL_ORDER_RE = re.compile(r"(?i)\b(?:chụp\s*(?:x-?quang\s*)?ngực\s*thẳng|ngực\s*thẳng|ngvc\s*th[aăäå]ng|nuôi\s*cấy|nuOi\s*cay|nuoi\s*cay|lo\s*lắng|Io\s*l[aăäå]ng|dễ\s*qua|dé\s*aua|uống|uong)\b")
PROTECTED_PATTERNS = {
    "ICD10": ICD_RE, "LAB_ANALYTE": LAB_RE, "MEASUREMENT": MEASURE_RE,
    "LIS": LIS_RE, "SPECIMEN_OR_SAMPLE_ID": SAMPLE_RE, "ROOM_OR_BED": ROOM_BED_RE,
    "CLINICAL_ORDER": CLINICAL_ORDER_RE,
}

CONTEXT_DICTIONARY: Dict[str, List[str]] = {
    "PATIENT_NAME": ["họ tên", "họ và tên", "họ tên người bệnh", "họ tên bệnh nhân", "hq ten"],
    "HEALTH_INSURANCE_ID": ["bhyt", "số thẻ bhyt"],
    "NATIONAL_ID": ["cccd", "cmnd", "số định danh cá nhân", "hộ chiếu"],
    "DATE_OF_BIRTH": ["sinh ngày", "ngày sinh"], "YEAR_OF_BIRTH": ["năm sinh", "ns"],
    "PHONE_NUMBER_VN": ["điện thoại người bệnh", "điện thoại người nhà", "số điện thoại người bệnh", "số điện thoại người nhà", "điện thoại số"],
    "ADDRESS_VN": ["địa chỉ", "thường trú", "tạm trú", "nơi ở", "xã, phường", "thôn, phố", "tỉnh, thành phố"],
    "RELATIVE_NAME": ["họ tên người nhà", "người nhà cần báo tin", "người cần báo tin"],
    "HEALTHCARE_STAFF_NAME": ["bác sĩ chỉ định", "bác sỹ chỉ định", "bs chỉ định", "xác nhận kết quả", "người in", "người lấy mẫu", "người nhận mẫu", "người làm xn", "người kí", "ký số bởi"],
}

PROPAGATE_TYPES = {"PATIENT_NAME", "RELATIVE_NAME", "HEALTH_INSURANCE_ID", "NATIONAL_ID", "HEALTHCARE_STAFF_NAME", "PERSON_NAME_UNCLASSIFIED"}

def normalize_text(text: str) -> str:
    return unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))

def _protected(span_text: str) -> bool:
    return any(rx.fullmatch(span_text.strip()) for rx in PROTECTED_PATTERNS.values())

def _fold(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())

def _strip_accents(s: str) -> str:
    s = s.replace("đ", "d").replace("Đ", "D").replace("ø", "o").replace("Ø", "O").replace("å", "a").replace("Å", "A").replace("ä", "a").replace("Ä", "A").replace("ö", "o").replace("Ö", "O").replace("ü", "u").replace("Ü", "U")
    return "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c))

_BAD_NAME_TOKENS_FOLDED = {
    "benh", "vien", "truong", "khoa", "phong", "giuong", "buong", "ngay", "nam", "thang", "gio", "phut", "giay",
    "tuoi", "tubi", "tudi", "gioi", "kham", "chua", "dieu", "tri", "chan", "doan",
    "xet", "nghiem", "ket", "qua", "phieu", "trang", "tru", "luqng", "tich",
    "luurgng", "jurong", "crp", "glucose", "creatinin", "creatine", "got", "gpt", "ast", "alt",
    "wbc", "rbc", "plt", "hgb", "hct", "mcv", "mch", "mchc", "afb", "bhyt", "cccd", "cmnd",
    "ms", "kcb", "sid", "lis", "bs", "bscki", "bsckii", "wscki", "pgs", "ts", "ths", "ktv",
    "cn", "dd", "ds", "giam", "doc", "noi", "ngoai", "cap", "cuu", "hap", "vi", "sinh",
    "huyet", "hoc", "quang", "sieu", "am", "mach", "nhiet", "ap", "nhip",
    "tho", "nang", "chieu", "bmi", "cong", "toan", "bang", "ke",
    "chi", "phi", "dich", "vu", "thuoc", "vat", "tu", "mau", "nuoc", "tieu", "dom", "phoi",
    "tim", "gan", "lach", "bung", "kinh", "tai", "mui", "hong", "rang", "ham", "mat",
    "thuc", "hien", "chuy", "chuyen", "lo", "lang", "de", "qua", "nuoi", "cay",
    "nguc", "chup", "xquang", "uong", "tiem", "truyen", "dung", "lieu", "don",
    "latex", "hiqn", "tai", "on", "dinh", "trieu", "chung", "dau", "sot", "ho", "kho",
    "nhuom", "soi", "khang", "do"
}

def _valid(entity: str, value: str) -> bool:
    v = _fold(value)
    if not v or _protected(value):
        return False
    v_ascii = _strip_accents(v)
    if entity in {"PATIENT_NAME", "HEALTHCARE_STAFF_NAME", "PERSON_NAME_UNCLASSIFIED", "PERSON_NAME"}:
        if v in NAME_BAD_WORDS or v_ascii in NAME_BAD_WORDS or any(x in v_ascii for x in (
            "benh an", "benh vien", "truong dai hoc", "hoc y ha noi", "trung uong",
            "kham benh", "chi dinh", "chuyen khoa", "xet nghiem", "so y te",
            "khoa noi", "khoa ngoai", "khoa cap cuu", "khoa ho hap", "ke hoach tong hop",
            "nguoi duyet", "giam doc", "truong khoa", "dinh luong", "dinh luqng", "dinh jurong",
            "trang i", "trang 1", "chan doan", "ket qua", "yeu cau"
        )):
            return False
        if any(ch.isdigit() for ch in value) or ":" in value or "_" in value or "/" in value:
            return False
        toks_ascii = [re.sub(r"[^a-z]", "", t) for t in v_ascii.split()]
        toks_ascii = [t for t in toks_ascii if t]
        if not (1 <= len(toks_ascii) <= 7):
            return False
        if len(toks_ascii) == 1:
            # Allow 1-token only if it looks like a merged full name (>= 6 chars, e.g. TRINHVÅNHVdNG)
            if len(toks_ascii[0]) < 6 or toks_ascii[0] in _BAD_NAME_TOKENS_FOLDED:
                return False
        else:
            if any(t in _BAD_NAME_TOKENS_FOLDED for t in toks_ascii if len(t) >= 3) and not (
                len(toks_ascii) >= 2 and toks_ascii[0] in SURNAMES and not any(t in {"benh", "vien", "truong", "khoa", "trang", "crp", "jurong", "luqng", "luong", "xet", "nghiem", "phieu", "ms", "noi"} for t in toks_ascii)
            ):
                return False
            if all(len(t) <= 2 for t in toks_ascii):
                return False
            # Reject single-letter Roman numerals or page markers like "Trang I", "L CS", "C KL"
            if toks_ascii[0] in {"trang", "muc", "phan", "to", "so", "loai"} or (len(toks_ascii) == 2 and min(len(toks_ascii[0]), len(toks_ascii[1])) == 1):
                return False
    if entity == "RELATIVE_NAME":
        if v in NAME_BAD_WORDS or len(v) < 3:
            return False
    if entity == "HEALTH_INSURANCE_ID":
        cleaned = re.sub(r"[\s-]", "", value)
        if not re.fullmatch(r"[A-Z]{2}[0-9]{11,14}", cleaned, re.I):
            return False
    if entity == "ADDRESS_VN":
        labels=re.sub(r'[\s:;,.()/]+',' ',v_ascii).strip()
        phrase=r'(?:s[od6]\s+nha|thon\s+ph[o6]|xa\s+phuong|tinh\s+thanh\s+ph[o6]|huyen\s+q\s+tx|dia\s+chi(?:\s+hien\s+tai)?|thuong\s+tru|tam\s+tru|noi\s+o|s[o06]\s+the)'
        if re.fullmatch(phrase+r'(?:\s+'+phrase+r')*',labels):
            return False
        if v.startswith(ADDRESS_BAD_PREFIXES) or ":" in value[:25]:
            return False
        if v in {"việt nam", "viet nam", "kinh", "tự do", "nghe do"}:
            return False
    return True

_FIELD_BOUNDARY = re.compile(
    r"(?i)\s+(?=(?:"
    r"2\s*[.,_]?\s*sinh\s*ng[aàäå]y|n[aăäå]m\s*sinh|" + DOB_LABEL + r"|"
    r"gi[oớöi(y&a-z]{2,5}\s*t[ií]nh|nam\s*/\s*n[uữü]|"
    r"t\s*u\s*[oôơöổbdu]{1,2}\s*i|"
    r"[dđ][iị]a\s*ch[iỉ]|diachi|[dđ]i[eêéèệ]n\s*(?:th|[aåä])o[aạäå]i|"
    r"khoa(?:/ph[oòö]ng)?|m[aãäå]\s*(?:bn|h[oồö]\s*s[oơ]|ng[uư][oờ]i\s*b[eệ]nh)|"
    r"\(?\d{1,2}\)?\s*m[aãäå]\s*khu(?:\s*v[uự]c)?\s*(?=[(:：])|"
    r"(?:ph[oòö]ng|gi[uư][oờö]ng|bu[oồö]ng)\s*[:：]|"
    r"ch[aẩåä]n\s*[dđ]o[aáåä]n|(?:s[oố6]\s*(?:th[eéẻ]\s*)?)?bh[yv]t|th[oờö]i\s*gian|ng[aàäå]y\s*in|"
    r"t[iỉ]nh\s*,?\s*th[aàäå]nh\s*ph[oố6]"
    r")\s*[:：]?)"
)
_FIELD_LABEL = re.compile(
    r"(?i)^\s*(?:[-•*]\s*)?(?:[\(\[]?[0-9I\s]{1,5}[\)\]]?[.,_\-\s]*)?(?:"
    r"h[oọqp.]*\s*(?:v[aàåä]\s*)?t[eêéèio]n(?:\s*(?:ng[uưrờiö&a-z•,]*\s*)?b[eệ$?a-zÀ-ỹ]+(?:\s*nh[aâåä]n)?)?(?:\s*[\(\[f][^\)\]:\n]{0,20}[\)\]])?|"
    r"h[oọ]\s*t[eê]n,?\s*[dđ][iị]a\s*(?:ch[iỉ]\s*)?ng[uưrờiö&(y\s*a-zA-ZÀ-ỹ]+\s*nh[aàåä](?:\s*khi\s*c[aầåä]n\s*b[aáåäio]+\s*tin)?|"
    r"h[oọq.]+\s*t[eê]n,?\s*dia\s*chi\s*ngu[oờö&(y\s*a-z]+\s*nh[aàåä](?:\s*khi\s*c[aầåä]n\s*b[aáåäio]+\s*tin)?|"
    r"h[oọ]\s*t[eê]n\s*người\s*nhà|người\s*(?:nhà|liên\s*hệ|cần\s*báo\s*tin)|"
    r"b[aáåä]c\s*s[ĩỹi]\s*(?:ch[iỉ]\s*[dđ][iị]nh|[dđ]i[eề]u\s*tr[iị])|bs\s*ch[iỉ]\s*[dđ][iị]nh|"
    r"ng[uưrờiö(y]+\s*(?:l[aấåä]y\s*m[aẫåä]u|nh[aậäåü]n\s*m[aẫåä]u|l[aàåä]m\s*xn|xn|l[aậåä]p\s*phi[eế]u|in|k[iíyý]|duy[eệ]t\s*kq)|"
    r"k\s*tv\s*th[uựv•c\s]+hi[eệ?n]+|(?:[dđ]i[eề]u\s*)?d[uư][oơởỡö]ng(?:\s*th[uựy]c\s*hi[eệ]n)?|"
    r"k[yý]\s*s[oố]\s*b[oở]i|"
    r"[dđ][iị]a\s*ch[iỉ](?:\s*hi[eệ$]n\s*t[aạo]i)?|diachi|thường\s*trú|tạm\s*trú|nơi\s*ở|" + DOB_LABEL +
    r")\s*[:：;]\s*"
)
_INLINE_PATIENT_LABEL = re.compile(
    r"(?i)(?:^|\s|(?<=:))(?:"
    r"h[oọq]\s*(?:v[aàåä]\s*)?b[eệéèê]nh\s*nh[aâåä]n\s*[:：]|"
    r"t[eê]n\s+(?:b[eệéèê]nh\s*nh[aâåä]n|ng[uư][oờö]i\s*b[eệ]nh)\s*[:：]|"
    r"(?:[0-9I]{1,2}[.,_\-\s]*)?h[oọqp.]*\s*(?:v[aàåä]\s*)?t[eêéèio]n[ \t]+(?=(?-i:[A-ZÀ-ỸĐ]))|"
    r"(?:[0-9I]{1,2}[.,_\-\s]*)?h[oọqp.]*\s*(?:v[aàåä]\s*)?t[eêéèio]n(?:\s*(?:ng[uưrờiö&a-z•,]*\s*)?b[eệ$?a-zÀ-ỹ]+(?:\s*nh[aâåä]n)?)?(?:\s*[\(\[f][^\)\]:\n]{0,20}[\)\]])?\s*[:：]|"
    r"(?:[0-9I]{1,2}[.,_\-\s]*)?h[oọqp.]+\s*(?:v[aàåä]\s*)?t[eêéèio]n(?:\s+(?:ng[uưrờiö&a-z•,]*\s*)?b[eệ$?a-zÀ-ỹ]+(?:\s*nh[aâåä]n)?)(?:\s*[\(\[f][^\)\]:\n]{0,20}[\)\]])?\s*[:：]?|"
    r"\(\s*1\s*\)\s*(?:h[oọqp.]*\s*(?:v[aàåä]\s*)?t[eêéèio]n\s*)?(?:ng[uưrờiö&a-z•,]*\s*)?b[eệ$?a-zÀ-ỹ]+\s*[:：]|"
    r"(?:t[eê]n\s+t[oôö]i\s+l[aàåä]|l[aàåä]\s+ng[uưtrờiö]+\s*b[eệ]nh(?:\s*/\s*[dđ][aạ]i\s*di[eệ]n\s*gia\s*[dđ][iì]nh\s*ng[uưtrờiö]+\s*b[eệ]nh)?)\s*[:：]"
    r")[ \t\xa0]*"
)
_RELATIVE_LABEL = re.compile(r"(?i)(?:người\s*nhà|người\s*liên\s*hệ|người\s*cần\s*báo\s*tin)")
_OCR_DOCTOR_TITLE = r'B\.?[ \t]*S\.?[ \t]*(?:C[ \t]*(?:K[ \t]*[IL12]{1,3})?)?'
_NAME_START = re.compile(r"(?i)^(?:(?:PGS|GS|TS|ThS|BSNT|"+_OCR_DOCTOR_TITLE+r"|BSCKII|BSCKI|BSCK|WSCKI|CKII|CKI|BS|CN|C\.N|CS\.|K\s*TV|ĐD|DS)(?:\.|(?=\s))\s*)+")
_HEADING = re.compile(r"(?i)^(?:phiếu|bệnh\s*án|khám\s*bệnh|chỉ\s*định|người\s*bệnh|bệnh\s*phẩm|chẩn\s*đoán|xét\s*nghiệm|giới\s*tính|khoa|phòng|mã|số|ngày|năm|điện\s*thoại|họ\s*tên|địa\s*chỉ|bác\s*sĩ|ký\s*tên|kí\s*tên|lưu\s*ý|hướng\s*dẫn|điều\s*trị|trưởng\s*khoa|giám\s*đốc)\b")
_SIG_HEADING = re.compile(
    r"(?i)^\s*(?:"
    r"gi[aáåäi]m\s*[dđ][oốö]c(?:\s*b[eệ]nh\s*vi[eệ]n)?|"
    r"(?:t/?l\.?\s*)?tr[uư][oơở]ng\s*khoa|"
    r"b[aáåäi]c\s*s[ĩỹiy']*?\s*(?:l[aàåä]m\s*b[eệ]nh\s*[aáåäi]n|[dđ]i[eềa]u\s*tr[iị]|kh[aáåä]m\s*b[eệ]nh|ch[iỉ]\s*[dđ][iị]nh|chuy[eê]n\s*khoa)|"
    r"ng[uư][oơờ]i\s*(?:giao\s*h[oồö]\s*s[oơc]|nh[aậäå]n\s*h[oồö]\s*s[oơc]|duy[eệv]t\s*k[eế]t\s*qu[aảåä])|"
    r"x[aáåä]c\s*(?:nh[aậäå]n|mian)\s*c[uủü]a\s*ng[uưtcö1&a-z]+\s*b[eệ]nh"
    r")(?:\s*\(\d+\))?\s*$"
)
_OCR_MERGED_PATIENT_NAME = re.compile(r"^[^\W\d_]{6,28}$")

def _is_valid_patient_candidate(val: str) -> bool:
    if not val or _HEADING.match(val):
        return False
    if re.fullmatch(PERSON_NAME, val):
        return _valid("PATIENT_NAME", val)
    # Check OCR-merged patient name (e.g. "TRINHVÅNHVdNG") or slightly noisy OCR token
    if _OCR_MERGED_PATIENT_NAME.fullmatch(val):
        ascii_low = _strip_accents(val.lower())
        if any(ascii_low.startswith(sn) for sn in SURNAMES if len(sn) >= 2):
            return _valid("PATIENT_NAME", val)
    return False

def _field_findings(text: str) -> List[Finding]:
    lines = [m for m in re.finditer(r"[^\n]*", text) if m.group(0).strip()]
    found = []
    for idx, lm in enumerate(lines):
        line = lm.group(0)
        if WATERMARK_RE.match(line):
            continue
        if re.match(r"(?i)^\s*(?:[dđ]i[eề]u\s*)?d[uư][oơởö]ng(?:\s*th[uựy]c\s*hi[eệ]n)?\s*[:：;]\s*", line):
            m = re.match(r"(?i)^\s*(?:[dđ]i[eề]u\s*)?d[uư][oơởö]ng(?:\s*th[uựy]c\s*hi[eệ]n)?\s*[:：;]\s*", line)
        else:
            m = _FIELD_LABEL.match(line)
        if not m:
            # The explicit upper-case-name instruction disambiguates OCR's Họ -> 10.
            m = re.match(r'(?i)^\s*[0-9I.,\- ]*(?:h[oọ0]|10)\s*t[eêé]n\s*\(\s*in\s*hoa\s*\)\s*[:：]\s*', line)
        if not m:
            m = re.search(
                r"(?i)\b(?:ng[uưrờiö(yb]+\s*(?:in|nh[aậäåü]n\s*m[aẫåä]u|l[aàåä]m\s*xn|xn|l[aấåä]y\s*m[aẫåä]u|k[iíyý]|duy[eệv]t\s*kq)|"
                r"k[yý]\s*s[oố]\s*b[oở]i|k\s*tv\s*th[uựv•c\s]+hi[eệ?n]+|[dđ]i[eề]u\s*d[uư][oơởö]ng(?:\s*th[uựy]c\s*hi[eệ]n)?)\s*[:：\-]?\s*",
                line,
            )
        if m:
            label = _strip_accents(line[m.start():m.end()].lower())
            entity = (
                'RELATIVE_NAME' if ('nguoi nha' in label or 'ngu&i nha' in label or 'bao tin' in label or 'lien he' in label) else
                'HEALTHCARE_STAFF_NAME' if any(k in label for k in ('bac s', 'bs ch', 'nguoi l', 'nguoi nh', 'nguoi in', 'nguoi xn', ' lam xn', ' nhan mau', ' lay mau', ' xn', 'nguoi k', 'ky so', 'duyet', 'ktv', 'k tv', 'duong')) else
                'ADDRESS_VN' if any(k in label for k in ('dia chi', 'diachi', 'thuong tru', 'tam tru', 'noi o')) else
                'DATE_OF_BIRTH' if 'sinh' in label else
                'PATIENT_NAME'
            )
            raw = line[m.end():]
            raw = _FIELD_BOUNDARY.split(raw, maxsplit=1)[0]
            if entity == 'HEALTHCARE_STAFF_NAME' and 'nguoi in' in label:
                raw = re.split(r"(?i),?\s*ngày\s*in\s*:", raw, maxsplit=1)[0]
            value = raw.strip(' \t\xa0,;')
            start = lm.start() + m.end() + len(raw) - len(raw.lstrip(' \t\xa0'))
            if not value and idx + 1 < len(lines) and lines[idx + 1].start() <= lm.end() + 2:
                next_raw = lines[idx + 1].group(0)
                nextline = next_raw.strip()
                if not WATERMARK_RE.match(nextline):
                    if entity == 'DATE_OF_BIRTH' and re.fullmatch(DATE, nextline):
                        value = nextline
                        start = lines[idx + 1].start() + len(next_raw) - len(next_raw.lstrip())
                    elif entity in {'PATIENT_NAME', 'RELATIVE_NAME', 'HEALTHCARE_STAFF_NAME'} and not _HEADING.match(nextline):
                        stripped_next = _NAME_START.sub('', nextline).strip()
                        if re.fullmatch(PERSON_NAME, stripped_next) or (entity == 'PATIENT_NAME' and _is_valid_patient_candidate(stripped_next)):
                            value = nextline
                            start = lines[idx + 1].start() + len(next_raw) - len(next_raw.lstrip())
            if entity in {'PATIENT_NAME', 'HEALTHCARE_STAFF_NAME'}:
                stripped = _NAME_START.sub('', value)
                start += len(value) - len(stripped)
                value = stripped.strip(' \t\xa0,;-')
                # Handle concatenated doctor names like "Đinh Thị Kim DungThS.BS Lê Minh Hằng"
                if not re.fullmatch(PERSON_NAME, value) and re.search(r"(?:ThS|TS|PGS|BS|CN)", value):
                    first_part = re.split(r"(?=(?:ThS|TS|PGS|BS|CN)\b)", value)[0].strip()
                    if re.fullmatch(PERSON_NAME, first_part):
                        value = first_part
                valid_name = _is_valid_patient_candidate(value) if entity == 'PATIENT_NAME' else (not _HEADING.match(value) and bool(re.fullmatch(PERSON_NAME, value)) and _valid(entity, value))
                if valid_name:
                    role = (
                        'DOCTOR' if ('bac s' in label or 'bs ch' in label or 'ky so' in label) else
                        'LAB_STAFF' if ('nguoi l' in label or 'nguoi nh' in label or 'ktv' in label or 'k tv' in label or 'dieu duong' in label) else 'UNKNOWN'
                    )
                    found.append(Finding(entity, start, start + len(value), 0.99, value, 'v20_strict_field', role=role))
            elif entity == 'RELATIVE_NAME':
                address_label=re.search(r'(?i)[ \t]+d[ \t]*/[ \t]*c[ \t]*[:：][ \t]*',value)
                if address_label:
                    address=value[address_label.end():].strip()
                    if address and _valid('ADDRESS_VN',address):
                        address_start=start+address_label.end()
                        found.append(Finding('ADDRESS_VN',address_start,address_start+len(address),.99,address,'relative_explicit_address'))
                    value=value[:address_label.start()].rstrip()
                if value and not _HEADING.match(value) and _valid(entity, value):
                    found.append(Finding(entity, start, start + len(value), 0.99, value, 'v20_strict_field'))
            elif entity == 'ADDRESS_VN':
                if value and len(value) >= 3 and not _HEADING.match(value) and _valid(entity, value):
                    found.append(Finding(entity, start, start + len(value), 0.99, value, 'v20_strict_field'))
            elif entity == 'DATE_OF_BIRTH':
                if re.fullmatch(DATE, value) and _valid(entity, value):
                    found.append(Finding(entity, start, start + len(value), 0.99, value, 'v20_strict_field'))

        # Also scan inline patient name anchors anywhere on the line (e.g. "Y tế: ... Họ tên bệnh: TRỊNH VĂN HƯỞNG")
        for pm in _INLINE_PATIENT_LABEL.finditer(line):
            raw_p = line[pm.end():]
            raw_p = _FIELD_BOUNDARY.split(raw_p, maxsplit=1)[0]
            raw_p = re.split(r"\s*\([^\)]*\)", raw_p, maxsplit=1)[0]
            val_p = raw_p.strip(' \t\xa0,;-')
            if not val_p:
                continue
            st_p = lm.start() + pm.end() + len(raw_p) - len(raw_p.lstrip(' \t\xa0,;-'))
            if _is_valid_patient_candidate(val_p):
                found.append(Finding('PATIENT_NAME', st_p, st_p + len(val_p), 0.99, val_p, 'v20_inline_patient_field'))
    return found

SURNAMES = {
    'nguyễn', 'trần', 'lê', 'phạm', 'hoàng', 'huỳnh', 'phan', 'vũ', 'võ', 'đặng',
    'bùi', 'đỗ', 'hồ', 'ngô', 'dương', 'lý', 'đinh', 'trịnh', 'tống', 'kiều', 'phùng',
    'cao', 'mai', 'đào', 'lương', 'tạ', 'tô', 'hà', 'chu', 'đoàn', 'quách', 'nông',
    'triệu', 'lưu', 'vương', 'trương', 'đồng', 'lâm',
    # ASCII/OCR-degraded surname variants
    'nguyen', 'tran', 'le', 'pham', 'hoang', 'huynh', 'vu', 'vo', 'dang', 'bui',
    'do', 'ho', 'ngo', 'duong', 'ly', 'dinh', 'trinh', 'rieu', 'trieu', 'luong',
    'dao', 'dong', 'truong', 'vuong', 'luu', 'doan', 'quach', 'nong', 'lam', 'ta',
    'to', 'ha', 'chu', 'cao', 'mai', 'tong', 'kieu', 'phung', 'phan'
}
_TITLE = r'(?:(?:PGS|GS|TS|ThS|BSNT|'+_OCR_DOCTOR_TITLE+r'|BSCKII|BSCKI|BSCK|WSCKI|CKII|CKI|BS|CN|C\.N|CS\.|K[ \t]*TV|ĐD|DS)\.?[ \t\xa0•.\-]*)+'
_CASE_TOKEN = r'[A-Za-zÀ-ỸĐà-ỹđ0-9"\'.•\-\?]*'
_TITLE_NAME = re.compile(r'(?<!\w)((?i:' + _TITLE + r'))([A-Za-zÀ-ỸĐà-ỹđ][A-Za-zÀ-ỹĐđ0-9"\'.•\-\?!*]*(?:[ \t\xa0•]+(?!(?i:'+_TITLE+r'))[A-Za-zÀ-ỸĐà-ỹđ][A-Za-zÀ-ỹĐđ0-9"\'.•\-\?!*]*){0,6})(?!\w)')

def valid_titled_staff(value):
    if _valid('HEALTHCARE_STAFF_NAME',value):return True
    parts=value.split()
    if not 3<=len(parts)<=5:return False
    first=re.sub('[^a-z]','',_strip_accents(parts[0].lower())).replace('rn','m')
    if len(first)<3 or first in _BAD_NAME_TOKENS_FOLDED or any(len(p)<2 for p in parts):return False
    if first in SURNAMES and _valid('HEALTHCARE_STAFF_NAME',first+' '+' '.join(parts[1:])):return True
    for surname in SURNAMES:
        if len(first)==len(surname):near=sum(a!=b for a,b in zip(first,surname))==1
        elif len(first)==len(surname)+1:near=any(first[:i]+first[i+1:]==surname for i in range(len(first)))
        elif len(surname)==len(first)+1:near=any(surname[:i]+surname[i+1:]==first for i in range(len(surname)))
        else:near=False
        if near and _valid('HEALTHCARE_STAFF_NAME',surname+' '+' '.join(parts[1:])):return True
    return False


def _staff_findings(text: str) -> List[Finding]:
    found = []
    flat,indices=_build_folded_index(text)
    for m in re.finditer(r'(?m)^la\s*nguoi\s*benh\s*/[^\n]{0,70}?nguoi\s*benh[.:•]+[ \t]*([^\n]+)',flat):
        a,b=indices[m.start(1)],indices[m.end(1)-1]+1;value=text[a:b].strip()
        if _is_valid_patient_candidate(value):found.append(Finding('PERSON_NAME',a,a+len(value),.99,value,'explicit_consent_identity_field'))
    identity_patterns=[
        ('PERSON_NAME',r'(?im)^[ \t]*(?:t[eéê]n[ \t]*t[oôö]i[ \t]*l[aàäå][ \t]*[:：][ \t]*|'+DATE+r'[ \t]+)?('+PERSON_NAME+r')[ \t]+sinh[ \t]*(?:n[aăäå]m|ng[aàäå]y)[ \t]*[:：][ \t]*('+DATE+'|'+YEAR+r')(?!\d)'),
        ('RELATIVE_NAME',r'(?im)\b(?:ch[aáàâåä]u|con[ \t]*trai|con[ \t]*g[aá]i|v[oợ]|ch[oồ]ng)[ \t]*[:：][ \t]*('+PERSON_NAME+r')')]
    for kind,pattern in identity_patterns:
        for match in re.finditer(pattern,text):
            value=match.group(1).strip();parts=value.split()
            if (parts and _strip_accents(parts[0].lower()) in SURNAMES and _valid('PERSON_NAME',value)
                and (all(p[0].isupper() for p in parts) or sum(ch.isupper() for ch in value)>.7*sum(ch.isalpha() for ch in value))):
                found.append(Finding(kind,match.start(1),match.start(1)+len(value),.99,value,'explicit_identity_birth_or_relative'))
                if match.lastindex==2:
                    birth=match.group(2);birth_kind='YEAR_OF_BIRTH' if len(birth)==4 else 'DATE_OF_BIRTH'
                    found.append(Finding(birth_kind,match.start(2),match.end(2),.99,birth,'explicit_identity_birth_value'))
    # 1. Capture watermark lines first
    for wm in WATERMARK_RE.finditer(text):
        val = wm.group(0).strip()
        start = wm.start() + len(wm.group(0)) - len(wm.group(0).lstrip())
        found.append(Finding('WATERMARK_TEXT', start, start + len(val), 0.995, val, 'v20_watermark_line'))

    # 2. Capture title + name (e.g. BSCKII. Nguyễn Văn Thuyền, C.N. Dương Thị Phương, ThS. Phan Văn Hiếu)
    for m in _TITLE_NAME.finditer(text):
        value = m.group(2).strip(" .,:;")
        start = m.start(2)
        boundary=re.search(r'(?i)[ \t]+th[uư]\s*(?:k[yý]|icy)\s*[:：]',text[start:])
        if boundary and boundary.start()<len(value):value=value[:boundary.start()].rstrip()
        end = start + len(value)
        # Check for wrapped 1-2 given-name syllables on the next line (e.g. "ThS.BS Lê Minh\nHằng" or "BSCKI. Döng\nManh Cuöng")
        tail_m = re.match(r"[ \t\xa0]*\n[ \t\xa0]*([A-ZÀ-ỸĐ][A-Za-zÀ-ỹĐđ'.•\-]{1,12}(?:[ \t\xa0]+[A-ZÀ-ỸĐ][A-Za-zÀ-ỹĐđ'.•\-]{1,12})?)(?=[ \t\xa0]*(?:\n|$))", text[end:])
        if tail_m:
            w_tok = tail_m.group(1)
            if not _HEADING.match(w_tok) and not _NAME_START.match(w_tok) and _valid('HEALTHCARE_STAFF_NAME', w_tok if len(w_tok.split()) >= 2 else (value + " " + w_tok)):
                end = end + tail_m.end(1)
                value = text[start:end]
        tokens = value.split()
        if any(t in {'CK', 'UB', 'MRI', 'CT', 'GPB', 'HC', 'XN', 'KCB', 'BHYT', 'MS', 'NOI'} for t in tokens):
            continue
        if len(tokens) == 1:
            v_low = _strip_accents(value.lower())
            # Single-token staff name after title must be at least 3 chars, capitalized, and not a bad word
            if len(value) < 3 or not value[0].isupper() or v_low in _BAD_NAME_TOKENS_FOLDED or v_low in NAME_BAD_WORDS or not value.isalpha():
                continue
            score = 0.85
        elif valid_titled_staff(re.sub(r"[•\?!*]+", "", value)):
            score = 0.99
        else:
            continue
        role = (
            'DOCTOR' if re.search(r'BS|BSNT|CKI', m.group(1), re.I) else
            'TECHNICIAN' if re.search(r'K\s*TV|CN|C\.N', m.group(1), re.I) else
            'NURSE' if 'ĐD' in m.group(1) else 'UNKNOWN'
        )
        found.append(Finding('HEALTHCARE_STAFF_NAME', start, end, score, value, 'v20_title_name', role=role))

    # A printed name label can sit in a table row and lose its colon during OCR.
    for m in re.finditer(r'(?im)\bh[oọq]\s*(?:v[aà]\s*)?t[eêéèiaâă]n[ \t]*[:：]?[ \t]+('+PERSON_NAME+r')[ \t]*$',text):
        value=m.group(1).strip();parts=value.split()
        if (parts and _strip_accents(parts[0].lower()) in SURNAMES
                and all(p[0].isupper() for p in parts) and _valid('PERSON_NAME',value)):
            found.append(Finding('PERSON_NAME',m.start(1),m.start(1)+len(value),.99,value,'explicit_name_label_ocr'))

    # 3. Capture names below signature headings (Giám đốc bệnh viện, Trưởng khoa, BÁC SĨ ĐIỀU TRỊ, etc.)
    lines = [m for m in re.finditer(r"[^\n]+", text) if m.group(0).strip()]
    for idx, lm in enumerate(lines):
        sline = lm.group(0).strip()
        if _SIG_HEADING.match(sline):
            for look_ahead in range(1, 5):
                if idx + look_ahead >= len(lines):
                    break
                cand_match = lines[idx + look_ahead]
                cand_raw = cand_match.group(0)
                cand = cand_raw.strip()
                if WATERMARK_RE.match(cand) or cand.startswith("chu_ky_"):
                    continue
                if _SIG_HEADING.match(cand):
                    break
                # Strip optional "Họ và tên:" or title prefix
                cand_clean = re.sub(r"(?i)^(?:h[oọ]\s*(?:v[aà]\s*)?t[eêi]n\s*:\s*)", "", cand)
                cand_clean = _NAME_START.sub("", cand_clean).strip()
                parts = cand_clean.split()
                if 2 <= len(parts) <= 6 and re.fullmatch(PERSON_NAME, cand_clean) and _valid('HEALTHCARE_STAFF_NAME', cand_clean):
                    offset = cand_raw.find(cand_clean)
                    if offset >= 0:
                        st = cand_match.start() + offset
                        found.append(Finding('HEALTHCARE_STAFF_NAME', st, st + len(cand_clean), 0.99, cand_clean, 'v20_sig_heading_name', role='DOCTOR'))
                        break

    # 4. Unlabelled uppercase or Title-Case standalone Vietnamese names (including optional date/time or label prefix)
    for m in re.finditer(r'(?m)^[ \t\xa0]*(?:(?:[^\n:]{1,40}:\s*)|(?:\d{1,2}\s*/\s*\d{1,2}(?:\s*/\s*\d{4})?\s+)?(?:\d{1,2}\s*:\s*\d{2}\s+)?(?:\d{1,2}\s+)?)?([^\n:]+?)[ \t\xa0]*$', text):
        raw = m.group(1)
        if WATERMARK_RE.match(raw):
            continue
        value = _NAME_START.sub("", raw.strip()).strip()
        tokens = value.split()
        if (2 <= len(tokens) <= 7
                and _strip_accents(tokens[0].lower()) in SURNAMES
                and (value == value.upper() or all(t[0].isupper() for t in tokens))
                and re.fullmatch(PERSON_NAME, value)
                and _valid('HEALTHCARE_STAFF_NAME', value)):
            offset = raw.find(value)
            start = m.start(1) + (offset if offset >= 0 else len(raw) - len(raw.lstrip()))
            found.append(Finding('PERSON_NAME_UNCLASSIFIED', start, start + len(value), 0.75, value, 'v20_unlabelled_person_review:CONTEXT_REQUIRED_REVIEW', 'CONTEXT_REQUIRED'))
    return found

def _normalize_with_map(text: str):
    normalized = []; mapping = []; i = 0
    while i < len(text):
        start = i
        if text[i] == '\r':
            i += 2 if text[i:i+2] == '\r\n' else 1
            cluster = '\n'
        else:
            i += 1
            while i < len(text) and unicodedata.combining(text[i]):
                i += 1
            cluster = unicodedata.normalize('NFC', text[start:i])
        normalized.append(cluster)
        mapping.extend([(start, i)] * len(cluster))
    return ''.join(normalized), mapping

def _restore(f: Finding, original: str, mapping):
    if not 0 <= f.start < f.end <= len(mapping):
        raise ValueError('Invalid finding offsets')
    a, b = mapping[f.start][0], mapping[f.end - 1][1]
    return Finding(f.entity_type, a, b, f.score, original[a:b], f.rule, f.review_status, f.role)

def _deduplicate(findings):
    best = {}
    for f in findings:
        key = (f.start, f.end)
        if key not in best or f.score > best[key].score:
            best[key] = f
    return sorted(best.values(), key=lambda f: (f.start, f.end, f.entity_type))

def analyze_hmu_text(text: str) -> List[Finding]:
    normalized, mapping = _normalize_with_map(text)
    return _deduplicate([_restore(f, text, mapping) for f in _analyze_normalized_text(normalized)])

def analyze_hmu_document(page_texts: List[str], external_seeds: Optional[Dict[str, List[str]]] = None, *, _finding_validator=None):
    originals = list(page_texts)
    pairs = [_normalize_with_map(t) for t in originals]
    validators = None if _finding_validator is None else [
        lambda f, pn=pn, original=original, mapping=mapping: _finding_validator(pn, _restore(f, original, mapping))
        for pn,(original,(_,mapping)) in enumerate(zip(originals,pairs))]
    findings, known = _analyze_normalized_document([t for t, _ in pairs], external_seeds=external_seeds, _page_validators=validators)
    return [_deduplicate([_restore(f, original, mapping) for f in fs])
            for original, (_, mapping), fs in zip(originals, pairs, findings)], known

def protected_hits(text: str):
    normalized, mapping = _normalize_with_map(text)
    return [(kind, mapping[a][0], mapping[b - 1][1], text[mapping[a][0]:mapping[b - 1][1]])
            for kind, a, b, _ in _protected_normalized_hits(normalized)]

_ADDRESS_PART_LABEL = re.compile(r'(?i)\b(?:s[oố6d]\s*nh[aàåä]|th[oôö]n\s*,?\s*ph[oố6]|x[aãäå]\s*,?\s*ph[uưü][oờö]ng|t[iỉ]nh\s*[-,.]?\s*(?:[tf]{1,2}[aàåä]nh\s*)?ph[oố6]|huy[eệ]n\s*\([^\n)]{1,8}\))\s*[:：]?\s*')


def split_address_findings(text,findings):
    result=[]
    for f in findings:
        if f.entity_type!='ADDRESS_VN':result.append(f);continue
        labels=list(_ADDRESS_PART_LABEL.finditer(text,f.start,f.end))
        if not labels:result.append(f);continue
        start=f.start
        for label in labels+[None]:
            end=label.start() if label else f.end
            boundary=_FIELD_BOUNDARY.search(text,start,end)
            if boundary:end=boundary.start()
            value=text[start:end].strip(' \t,;:')
            if value and _valid('ADDRESS_VN',value):
                a=text.find(value,start,end)
                result.append(Finding('ADDRESS_VN',a,a+len(value),f.score,value,f.rule))
            if label:start=label.end()
    for label in _ADDRESS_PART_LABEL.finditer(text):
        end=text.find('\n',label.end());end=len(text) if end<0 else end
        following=_ADDRESS_PART_LABEL.search(text,label.end(),end)
        if following:end=following.start()
        boundary=_FIELD_BOUNDARY.search(text,label.end(),end)
        if boundary:end=boundary.start()
        value=text[label.end():end].strip(' \t,;:')
        if value and _valid('ADDRESS_VN',value):
            a=text.find(value,label.end(),end)
            result.append(Finding('ADDRESS_VN',a,a+len(value),.97,value,'explicit_address_part_value'))
    return result


def _analyze_normalized_text(text: str) -> List[Finding]:
    findings: List[Finding] = _field_findings(text) + _staff_findings(text)
    for entity, rule_name, regex, score, group in RULES:
        for m in re.finditer(regex, text, flags=re.MULTILINE):
            start, end = m.span(group)
            if rule_name=='patient_age_postfix' and re.search(r'\d[ \t|]*$',text[:start]):
                continue
            if rule_name=='patient_age_postfix' and not re.search(r'(?:benh\s*nhan|nguoi\s*benh|\bbn)\s*(?:nam|nu)?\s*$',_strip_accents(text[max(0,start-60):start].lower())):
                continue
            if entity == 'PATIENT_AGE' and not re.search(r'[:：]',text[m.start():start]) and re.search(r'\d[ \t]*$',text[:m.start()]):
                continue
            raw = text[start:end]
            left = len(raw) - len(raw.lstrip()); right = len(raw) - len(raw.rstrip())
            start += left; end -= right
            value = text[start:end]
            if entity == 'ADDRESS_VN':
                boundary = _FIELD_BOUNDARY.search(text,start)
                if boundary and boundary.start() < end:
                    end = boundary.start()
                    while end > start and text[end-1].isspace(): end -= 1
                    value=text[start:end]
            if entity == 'RELATIVE_NAME':
                address_label=re.search(r'(?i)[ \t]+d[ \t]*/[ \t]*c[ \t]*[:：][ \t]*',value)
                if address_label:
                    address=value[address_label.end():].strip()
                    if address and _valid('ADDRESS_VN',address):
                        address_start=start+address_label.end()
                        findings.append(Finding('ADDRESS_VN',address_start,address_start+len(address),score,address,'relative_explicit_address'))
                    value=value[:address_label.start()].rstrip()
                    end=start+len(value)
            if entity == "HEALTHCARE_STAFF_NAME":
                stripped = _NAME_START.sub("", value)
                start += len(value) - len(stripped)
                value = stripped.strip()
            if _valid(entity, value) or rule_name=='insurance_missing_prefix_ocr':
                findings.append(Finding(entity, start, end, score, value, rule_name))
    findings=split_address_findings(text,findings)
    best = {}
    for f in findings:
        key = (f.entity_type, f.start, f.end)
        if key not in best or f.score > best[key].score:
            best[key] = f
    return sorted(best.values(), key=lambda x: (x.start, x.end, x.entity_type))

def build_document_identifiers(page_texts: Iterable[str], external_seeds: Optional[Dict[str, List[str]]] = None, _cached_page_findings: Optional[List[List[Finding]]] = None) -> Dict[str, List[str]]:
    page_texts = list(page_texts)
    page_fs_list = _cached_page_findings if _cached_page_findings is not None else [analyze_hmu_text(t) for t in page_texts]
    vals: Dict[str, set] = {k: set() for k in PROPAGATE_TYPES}
    watermark_names = set()
    patient_candidates: List[str] = []
    for text, fs in zip(page_texts, page_fs_list):
        for wm in WATERMARK_RE.finditer(text):
            watermark_names.add(wm.group(1).strip())
        for f in fs:
            if f.rule=='insurance_missing_prefix_ocr':continue  # Missing-prefix OCR is trusted only at its card label.
            if f.review_status != 'CONTEXT_REQUIRED' and f.entity_type in PROPAGATE_TYPES and f.score >= (0.97 if f.entity_type in {"HEALTHCARE_STAFF_NAME", "PERSON_NAME_UNCLASSIFIED"} else 0.99):
                val = f.text.strip()
                if val not in watermark_names:
                    vals[f.entity_type].add(val)
                    if f.entity_type == "PATIENT_NAME":
                        patient_candidates.append(val)
    if patient_candidates:
        # Collect all valid patient name forms, prioritizing multi-word canonical forms first
        multi_word = [p for p in patient_candidates if len(p.split()) >= 2]
        canonical = multi_word[0] if multi_word else patient_candidates[0]
        kept = {canonical}
        canon_compact = re.sub(r"[^a-z]", "", _strip_accents(canonical.lower()))
        for p in patient_candidates:
            p_compact = re.sub(r"[^a-z]", "", _strip_accents(p.lower()))
            if p_compact == canon_compact or (len(p_compact) >= 6 and len(canon_compact) >= 6 and p_compact[:4] == canon_compact[:4]):
                kept.add(p)
        vals["PATIENT_NAME"] = kept
    else:
        vals.pop("PATIENT_NAME", None)
    if external_seeds:
        for k, vlist in external_seeds.items():
            if k in vals:
                vals[k].update(x.strip() for x in vlist if x and x.strip())
            elif vlist:
                vals[k] = {x.strip() for x in vlist if x and x.strip()}
    for k in list(vals.keys()):
        vals[k] -= watermark_names
    # Upgrade any unclassified person names that were never labelled as PATIENT_NAME into HEALTHCARE_STAFF_NAME seeds if they appear in clinical context
    labelled_patients = vals.get('PATIENT_NAME', set())
    if 'PERSON_NAME_UNCLASSIFIED' in vals:
        vals['PERSON_NAME_UNCLASSIFIED'] -= labelled_patients | vals.get('HEALTHCARE_STAFF_NAME', set())
    return {k: sorted(v, key=lambda s: (len(s.split()) >= 2, len(s)), reverse=True) for k, v in vals.items() if v}

def _exact_flexible_pattern(value: str) -> re.Pattern:
    parts = [re.escape(p) for p in re.split(r"\s+", value.strip()) if p]
    return re.compile(r"(?<!\w)" + r"\s+".join(parts) + r"(?!\w)", re.IGNORECASE)

_OCR_CHAR_EQUIV = {
    "a": r"(?:a|q|u|d|o|c|e|4|å|ä|à|á)",
    "b": r"(?:b|h|d|p|6|8)",
    "c": r"(?:c|e|o|g|\()",
    "d": r"(?:d|b|o|cl|a|đ)",
    "e": r"(?:e|c|o|a|ê|é|è)",
    "g": r"(?:g|q|y|9)",
    "h": r"(?:h|ii|ll|fl|f1|n|b|li)",
    "i": r"(?:i|l|1|j|\!|\||í|ì)",
    "k": r"(?:k|lc|h)",
    "l": r"(?:l|i|1|\|)",
    "m": r"(?:m|rn|nn|nl|in)",
    "n": r"(?:n|u|m|ii|ll|h|r)",
    "o": r"(?:o|u|a|0|c|q|ö|ơ|ô)",
    "p": r"(?:p|b)",
    "q": r"(?:q|g|a|o)",
    "r": r"(?:r|t|n|v|c)",
    "s": r"(?:s|5)",
    "t": r"(?:t|f|i|l|\+)",
    "u": r"(?:u|v|o|n|a|ii|ll|lr|ü|ư|ú|ù)",
    "v": r"(?:v|u|y|w)",
    "x": r"(?:x|k)",
    "y": r"(?:y|v|g|i)",
}

def _ocr_char_regex(ch: str) -> str:
    return _OCR_CHAR_EQUIV.get(ch.lower(), re.escape(ch.lower()))

def _ocr_word_regex(word_ascii: str, allow_inner_space: bool = False) -> str:
    sep = r"[ \t'.•\-\?\+!]*" if allow_inner_space else r"['.•\-\?\+!]*"
    return sep.join(_ocr_char_regex(c) for c in word_ascii if c.isalpha())

def _compile_memorized_name_patterns(known: Dict[str, List[str]]) -> List[Tuple[str, re.Pattern, str, str]]:
    """Precompile once per document OCR-tolerant regexes for memorized Patient and Staff names."""
    compiled: List[Tuple[str, re.Pattern, str, str]] = []
    seen_sigs = set()

    # 1. Patient Name memorized patterns
    for pname in known.get("PATIENT_NAME", []):
        parts = [re.sub(r"[^a-z]", "", _strip_accents(p.lower())) for p in pname.split()]
        parts = [p for p in parts if p]
        if not parts:
            continue
        sig = "PAT:" + " ".join(parts)
        if sig in seen_sigs:
            continue
        seen_sigs.add(sig)
        if len(parts) >= 2:
            # Full name allowing merged spaces, newlines, or OCR substitutions (e.g. TRINHVÅNHVdNG, TRINH VAN IIUÖNG)
            full_rx_str = r"(?<!\w)" + r"[ \t\n'.•\-\?\+!*]*".join(_ocr_word_regex(p, allow_inner_space=False) for p in parts) + r"(?!\w)"
            compiled.append(("PATIENT_NAME", re.compile(full_rx_str, re.I), "memorized_patient_ocr_full", pname))
            # Surname + Given name (middle name dropped by OCR)
            if len(parts) >= 3:
                short_rx_str = r"(?<!\w)" + _ocr_word_regex(parts[0]) + r"[ \t]+" + _ocr_word_regex(parts[-1]) + r"(?!\w)"
                compiled.append(("PATIENT_NAME", re.compile(short_rx_str, re.I), "memorized_patient_ocr_short", pname))
            # Standalone given name on signature line (e.g. "*f1UöNG" at bottom of cost sheet)
            given = parts[-1]
            if len(given) >= 4:
                sig_given_rx = re.compile(r"(?m)^[ \t\xa0\*•\-\.]*([\*•\-\.]*" + _ocr_word_regex(given) + r")[ \t\xa0]*$", re.I)
                compiled.append(("PATIENT_NAME", sig_given_rx, "memorized_patient_given_signature", pname))

    # 2. Healthcare Staff Name memorized patterns (Doctor, Nurse, Technician)
    for staff_bucket in ("HEALTHCARE_STAFF_NAME", "PERSON_NAME_UNCLASSIFIED"):
        for sname in known.get(staff_bucket, []):
            parts = [re.sub(r"[^a-z]", "", _strip_accents(p.lower())) for p in sname.split()]
            parts = [p for p in parts if len(p) >= 2]
            if len(parts) < 2:
                continue
            sig = "STAFF:" + " ".join(parts)
            if sig in seen_sigs:
                continue
            seen_sigs.add(sig)
            # Full staff name across spaces or narrow column line-wraps (with optional inner space in last token like "N gqc", "n Thi\nHOåi")
            word_rxs = [_ocr_word_regex(p, allow_inner_space=(idx > 0)) for idx, p in enumerate(parts)]
            full_staff_str = r"(?<!\w)" + r"[ \t\n'.•\-\?\+!]+".join(word_rxs) + r"(?!\w)"
            compiled.append(("HEALTHCARE_STAFF_NAME", re.compile(full_staff_str, re.I), "memorized_staff_ocr_full", sname))
            if len(parts) >= 3:
                # Middle + Given name (e.g. "Manh Cubng", "Manh CLröng")
                mid_given_str = r"(?<!\w)" + _ocr_word_regex(parts[-2], allow_inner_space=False) + r"[ \t\n'.•\-\?\+!]+" + _ocr_word_regex(parts[-1], allow_inner_space=True) + r"(?!\w)"
                compiled.append(("HEALTHCARE_STAFF_NAME", re.compile(mid_given_str, re.I), "memorized_staff_mid_given", sname))
                # Surname + Given name (e.g. "Daug Cuong", "Dåo Thäm", "Då Thåm")
                sur_given_str = r"(?<!\w)" + _ocr_word_regex(parts[0], allow_inner_space=False) + r"[ \t\n'.•\-\?\+!]+" + _ocr_word_regex(parts[-1], allow_inner_space=True) + r"(?!\w)"
                compiled.append(("HEALTHCARE_STAFF_NAME", re.compile(sur_given_str, re.I), "memorized_staff_sur_given", sname))
                # Wrapped standalone last token on its own line (e.g. "\nN gqc", "\nHOåi", "\nThåm")
                given = parts[-1]
                if (len(given) >= 4 and given not in _BAD_NAME_TOKENS_FOLDED
                        and given not in {'thang', 'uong'}):
                    wrap_given_rx = re.compile(r"(?:^|\n)[ \t\xa0•'\-\.!0-9]*(" + _ocr_word_regex(given, allow_inner_space=True) + r")(?=[ \t\xa0]*(?:\n|$))", re.I)
                    compiled.append(("HEALTHCARE_STAFF_NAME", wrap_given_rx, "memorized_staff_wrapped_given", sname))
    return compiled

def _build_folded_index(text: str) -> Tuple[str, List[int]]:
    folded = []
    indices = []
    for i, ch in enumerate(text):
        chars = _strip_accents(ch.lower())
        for c in chars:
            folded.append(c)
            indices.append(i)
    return "".join(folded), indices


def _person_name_context(text, start, seed):
    prefix = _strip_accents(text[max(0, start - 120):start].lower())
    suffix=_strip_accents(text[start+len(seed):start+len(seed)+45].lower())
    if re.match(r'^[ \t().,:;-]*ngon[ \t]*(?:cai|tro|giua|ap|ut)\b',suffix):return True
    if any(m.end()==len(prefix) for m in _INLINE_PATIENT_LABEL.finditer(prefix)):
        return True
    label = (r'(?:^|\n)[ \t]*(?:(?:\d+[.)]|[-•])[ \t]*)?(?:bac\s*s[iy](?:\s*(?:dieu\s*tri|chi\s*dinh|kham\s*benh))?|\bbs(?:\s*ck[i12]*)?|'
             r'dieu\s*duong(?:\s*thuc\s*hien)?|nguoi\s*(?:in|ky|lam\s*xn|lay\s*mau)|\bcn|\bktv|'
             r'ho\s*(?:va\s*)?ten(?:\s*(?:nguoi\s*benh|benh\s*nhan|nguoi\s*nha))?(?:\s*\(in\s*hoa\))?|'
             r'ten\s*(?:benh\s*nhan|nguoi\s*benh)|'
             r'ten\s*toi\s*la|nguoi\s*(?:nha|lien\s*he|can\s*bao\s*tin))'
             r'[ \t]*(?:[:.\-]\s*|\n\s*)$')
    if re.search(label, prefix):
        return True
    # A learned prefix is evidence only when that prefix itself follows a personal-name field.
    parts = re.findall(r'[a-z]+', _strip_accents(seed.lower()))
    for count in (1, 2):
        preceding = parts[:-count]
        if preceding:
            match = re.search(r'(?<!\w)' + r'[\s.\-]*'.join(_ocr_char_regex(c) for c in ''.join(preceding)) + r'\s*$', prefix)
            if match and re.search(label, prefix[:match.start()]):
                return True
    return False


_MONEY_WORD = r'(?:khong|mot|met|hai|ba|bon|tu|nam|lam|sau|sciu|bay|tam|chin|muoi|mu[•.]ai|linh|le|tram|nghin|ngan|trieu|ty|ti)'
_CLINICAL_ALIAS_CONTEXT = re.compile(
    r'\b(?:(?:ho|hep)[ \t\xa0]+|sieu[ \t\xa0]+am[ \t\xa0]*:[ \t\xa0]*)van[ \t\xa0]+hai[ \t\xa0]+la\b|'
    r'\bvan[ \t\xa0]+hai[ \t\xa0]+la(?=[ \t\xa0]*(?::|doppler\b))|'
    r'\bkim\s+canh\s+(?:buom|budm|bu[•.]am|btr&m)\b|'
    r'\bdich\s+vu\s+theo\s+y(?:eu|ou)\s+cau\b|'
    r'\b(?:viet\s+bang\s+ch[ui]|bang\s+ch[ui])\s*:\s*(?:'+_MONEY_WORD+r'\s+){1,40}(?:dong|ddng)\b')


def _partial_alias_is_clinical(text, start, end):
    left=max(0,start-180);flat,indices=_build_folded_index(text[left:min(len(text),end+180)])
    return any(left+indices[m.start()]<=start and end<=left+indices[m.end()-1]+1
               for m in _CLINICAL_ALIAS_CONTEXT.finditer(flat))

def _check_name_geometry(findings, validator):
    for f in findings:
        if f.entity_type in {'PATIENT_NAME','RELATIVE_NAME','HEALTHCARE_STAFF_NAME','PERSON_NAME','PERSON_NAME_UNCLASSIFIED'} and not validator(f):
            f.score=.75;f.review_status='CONTEXT_REQUIRED'
            if 'GEOMETRY_REQUIRED_REVIEW' not in f.rule:f.rule+=':GEOMETRY_REQUIRED_REVIEW'
    return findings


def _analyze_normalized_document(page_texts: List[str], external_seeds: Optional[Dict[str, List[str]]] = None, *, _page_validators=None):
    texts = [normalize_text(x) for x in page_texts]
    cached_page_findings = [analyze_hmu_text(t) for t in texts]
    if _page_validators:
        for fs,validator in zip(cached_page_findings,_page_validators):_check_name_geometry(fs,validator)
    known = build_document_identifiers(texts, external_seeds=external_seeds, _cached_page_findings=cached_page_findings)
    years = {f.text for fs in cached_page_findings for f in fs if f.entity_type == "YEAR_OF_BIRTH"}
    if external_seeds and external_seeds.get("YEAR_OF_BIRTH"):
        years.update(external_seeds["YEAR_OF_BIRTH"])
    wm_prefixes = sorted({wm.group(1).strip() for t in texts for wm in WATERMARK_RE.finditer(t)}, key=len, reverse=True)
    wm_patterns = [
        (prefix, re.compile(r"(?m)^[ \t\xa0]*(" + re.escape(prefix[:8]) + r"[^\n]{0,35})[ \t\xa0]*$"))
        for prefix in wm_prefixes
    ]
    exact_known_patterns = [
        (entity, _exact_flexible_pattern(value), value)
        for entity, values in known.items()
        if (entity in PROPAGATE_TYPES or entity in {"DATE_OF_BIRTH", "ADDRESS_VN", "PHONE_NUMBER_VN"})
        for value in values if len(value) >= 3
    ]
    memorized_patterns = _compile_memorized_name_patterns(known)
    all_pages: List[List[Finding]] = []
    for text, base_fs in zip(texts, cached_page_findings):
        findings = [Finding(f.entity_type, f.start, f.end, f.score, f.text, f.rule, f.review_status, f.role) for f in base_fs]
        # Also catch truncated watermark fragments like "Hồ Thị M" or "Hồ Thị Min" on the same page
        for prefix, wm_rx in wm_patterns:
            for m in wm_rx.finditer(text):
                frag = m.group(1).strip()
                if prefix.startswith(frag) or frag.startswith(prefix):
                    findings.append(Finding("WATERMARK_TEXT", m.start(1), m.start(1) + len(frag), 0.99, frag, "v20_watermark_fragment"))
        for f in findings:
            if f.entity_type == "DATE_OF_BIRTH" and years and f.text[-4:] not in years:
                f.rule += ":DOB_YOB_CONFLICT_REVIEW"
        occupied = {(f.entity_type, f.start, f.end) for f in findings}
        for entity, rx, seed in exact_known_patterns:
            for m in rx.finditer(text):
                key = (entity, m.start(), m.end())
                if key in occupied:
                    continue
                candidate = m.group(0)
                if _valid(entity, candidate):
                    uncertain = entity in {'PATIENT_NAME','RELATIVE_NAME','HEALTHCARE_STAFF_NAME','PERSON_NAME_UNCLASSIFIED'} and not _person_name_context(text,m.start(),seed)
                    findings.append(Finding(entity, m.start(), m.end(), 0.75 if uncertain else 0.995, candidate,
                                            'document_exact_propagation' + (':CONTEXT_REQUIRED_REVIEW' if uncertain else ''),
                                            'CONTEXT_REQUIRED' if uncertain else 'PENDING_REVIEW'))
                    occupied.add(key)

        # Apply precompiled memorized OCR-tolerant Patient & Staff patterns on accent-folded text
        if memorized_patterns and text:
            flat, indices = _build_folded_index(text)
            for entity, rx, rule_name, seed in memorized_patterns:
                for m in rx.finditer(flat):
                    st_f, en_f = m.span(1) if m.lastindex else m.span(0)
                    if st_f >= en_f or en_f > len(indices):
                        continue
                    a, b = indices[st_f], indices[en_f - 1] + 1
                    while b < len(text) and unicodedata.combining(text[b]):
                        b += 1
                    key = (entity, a, b)
                    if key in occupied:
                        continue
                    cand_txt = text[a:b]
                    uncertain = not _person_name_context(text, a, seed)
                    if (uncertain and rule_name.startswith(('memorized_staff_mid_given','memorized_staff_sur_given','memorized_staff_wrapped_given'))
                            and _partial_alias_is_clinical(text,a,b)):continue
                    if not _protected(cand_txt):
                        if entity == "PATIENT_NAME":
                            valid = not _HEADING.match(cand_txt) if rule_name.startswith("memorized_patient") else (_is_valid_patient_candidate(cand_txt) or _valid(entity, cand_txt))
                        else:
                            valid = _valid(entity, cand_txt)
                        if valid:
                            findings.append(Finding(entity, a, b, 0.75 if uncertain else 0.99, cand_txt,
                                                    rule_name + (':CONTEXT_REQUIRED_REVIEW' if uncertain else ''),
                                                    'CONTEXT_REQUIRED' if uncertain else 'PENDING_REVIEW'))
                            occupied.add(key)

        findings.sort(key=lambda x: (x.start, x.end, x.entity_type))
        if _page_validators:_check_name_geometry(findings,_page_validators[len(all_pages)])
        all_pages.append(findings)
    return all_pages, known

def _parse_xml_tree_for_seeds(root_elem: ET.Element, seeds: Dict[str, set]):
    for elem in root_elem.iter():
        tag = elem.tag.upper().split("}")[-1]
        val = (elem.text or "").strip()
        if not val:
            continue
        if tag == "NOIDUNGFILE" and len(val) > 40:
            try:
                decoded = base64.b64decode(val).decode("utf-8", errors="ignore")
                sub = ET.fromstring(decoded)
                _parse_xml_tree_for_seeds(sub, seeds)
            except Exception:
                pass
        elif tag == "HO_TEN" and len(val.split()) >= 2:
            seeds["PATIENT_NAME"].add(unicodedata.normalize("NFC", val))
        elif tag in {"TEN_BS", "HO_TEN_BS", "THU_TRUONG_DV"} and len(val.split()) >= 2 and not any(c.isdigit() for c in val):
            seeds["HEALTHCARE_STAFF_NAME"].add(unicodedata.normalize("NFC", val))
        elif tag in {"HO_TEN_CHA", "HO_TEN_ME", "NGUOI_DAI_DIEN"} and len(val.split()) >= 2:
            seeds["RELATIVE_NAME"].add(unicodedata.normalize("NFC", val))
        elif tag == "NGAY_SINH" and len(val) >= 8 and val[:8].isdigit():
            y, m, d = val[:4], val[4:6], val[6:8]
            seeds["YEAR_OF_BIRTH"].add(y)
            seeds["DATE_OF_BIRTH"].add(f"{d}/{m}/{y}")
            seeds["DATE_OF_BIRTH"].add(f"{d}-{m}-{y}")
        elif tag == "DIA_CHI" and len(val) >= 4:
            full_addr = unicodedata.normalize("NFC", val)
            seeds["ADDRESS_VN"].add(full_addr)
            for part in re.split(r"[,;\-]", full_addr):
                p = part.strip()
                if len(p) >= 5 and _strip_accents(p.lower()) not in {"viet nam"}:
                    seeds["ADDRESS_VN"].add(p)
        elif tag == "DIEN_THOAI" and len(re.sub(r"\D", "", val)) >= 9:
            seeds["PHONE_NUMBER_VN"].add(val)
        elif tag == "SO_CCCD" and len(re.sub(r"\D", "", val)) >= 9:
            seeds["NATIONAL_ID"].add(val)
        elif tag == "MA_THE_BHYT" and len(val) >= 10:
            seeds["HEALTH_INSURANCE_ID"].add(val)

def build_case_xml_index(case_path):
    path=pathlib.Path(case_path).resolve();case_dir=path if path.is_dir() else path.parent
    xml_dirs=[case_dir]
    for anc in list(case_dir.parents)[:3]:
        if anc.name.lower() in {"temp","tmp","appdata","local","users","workspaces"} or anc.parent==anc:break
        xml_dirs.extend(c for c in anc.iterdir() if c.is_dir() and 'xml' in c.name.lower())
        if anc.name in {"1.DHYHN","2.BV71","3.BVQT","Database (Test-Case1)"}:break
    files=set()
    for directory in xml_dirs:
        files.update(directory.glob('*.xml') if directory.name.lower()=='pdf' else directory.rglob('*.xml'))
    candidates=[case_dir.name] + ([path.stem] if path.is_file() else [p.stem for p in case_dir.glob('*.pdf')])
    identities=[]
    for candidate in candidates:
        candidate=unicodedata.normalize('NFC',candidate)
        ident=re.search(r'(?<![0-9A-Za-z])(\d{8,12}|BA\d{6,12})(?![0-9A-Za-z])',candidate)
        if ident: identities.append(ident.group(1).lower())
        cleaned=re.sub(r'^(?:BA\d+|\d+)[\s_\-]+','',candidate).replace('_',' ').strip()
        if 2 <= len(cleaned.split()) <= 6 and re.fullmatch(PERSON_NAME,cleaned) and _valid('PATIENT_NAME',cleaned):
            identities.append(_strip_accents(cleaned.lower()))
    result=[]
    for xml_path in sorted(files):
        label=_strip_accents((xml_path.parent.name+' '+xml_path.name).replace('_',' ').lower())
        if not any(identity in label for identity in identities):continue
        parsed={k:set() for k in ('PATIENT_NAME','RELATIVE_NAME','HEALTHCARE_STAFF_NAME','DATE_OF_BIRTH','YEAR_OF_BIRTH','ADDRESS_VN','PHONE_NUMBER_VN','NATIONAL_ID','HEALTH_INSURANCE_ID')}
        try:
            _parse_xml_tree_for_seeds(ET.fromstring(xml_path.read_text(encoding='utf8',errors='ignore')),parsed)
        except (OSError,ET.ParseError):continue
        result.append((xml_path,parsed))
    return result


def extract_case_seeds(source_path, *, xml_index=None, source_name=None) -> Dict[str, List[str]]:
    """Extract ground-truth PII seeds from folder/filename and companion XML files."""
    path = pathlib.Path(source_path).resolve()
    case_dir = path if path.is_dir() else path.parent
    seeds: Dict[str, set] = {
        "PATIENT_NAME": set(),
        "RELATIVE_NAME": set(),
        "HEALTHCARE_STAFF_NAME": set(),
        "DATE_OF_BIRTH": set(),
        "YEAR_OF_BIRTH": set(),
        "ADDRESS_VN": set(),
        "PHONE_NUMBER_VN": set(),
        "NATIONAL_ID": set(),
        "HEALTH_INSURANCE_ID": set(),
    }
    # The upload basename supplies identity only, never a filesystem search path.
    if source_name is not None:
        import ntpath
        if not isinstance(source_name, str) or ntpath.basename(source_name) != source_name or source_name in {'.', '..'}:
            raise ValueError('Invalid source basename')
    # 1. Extract from directory name and PDF filename
    candidates = [pathlib.Path(source_name).stem] if source_name else [case_dir.name]
    if path.is_file() and not source_name:
        candidates.append(path.stem)
    case_id = None
    for cand in candidates:
        cand_nfc = unicodedata.normalize("NFC", cand)
        m_id = re.search(r"(?<![0-9A-Za-z])(\d{8,12}|BA\d{6,12})(?![0-9A-Za-z])", cand_nfc)
        if m_id and not case_id:
            case_id = m_id.group(1)
        # Strip numeric/BA prefixes and underscores/hyphens
        cleaned = re.sub(r"^(?:BA\d+|\d+)[\s_\-]+", "", cand_nfc).replace("_", " ").strip()
        if 2 <= len(cleaned.split()) <= 6 and re.fullmatch(PERSON_NAME, cleaned) and _valid("PATIENT_NAME", cleaned):
            seeds["PATIENT_NAME"].add(cleaned)

    if xml_index is None:
        xml_index = build_case_xml_index(path)
    patient_folded = {_strip_accents(n.lower()) for n in seeds["PATIENT_NAME"]}
    matches = 0
    for xml_p, parsed in xml_index:
        name_low = _strip_accents(xml_p.name.lower().replace("_", " "))
        parent_low = _strip_accents(xml_p.parent.name.lower().replace("_", " "))
        if (case_id and (case_id.lower() in name_low or case_id.lower() in parent_low)) or any(pf in name_low or pf in parent_low for pf in patient_folded if pf):
            for k, values in parsed.items(): seeds.setdefault(k,set()).update(values)
            matches += 1
            if matches >= 15: break

    return {k: sorted(v, key=len, reverse=True) for k, v in seeds.items() if v}

def _protected_normalized_hits(text: str):
    hits = []
    for kind, rx in PROTECTED_PATTERNS.items():
        for m in rx.finditer(text):
            hits.append((kind, m.start(), m.end(), m.group(0)))
    return sorted(hits, key=lambda x: x[1])

def to_presidio_results(text: str):
    from presidio_analyzer import RecognizerResult
    return [RecognizerResult(entity_type=f.entity_type, start=f.start, end=f.end, score=f.score)
            for f in analyze_hmu_text(text)]
