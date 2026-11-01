"""Phase 3B Gold families, part 4: Arabic- and mixed-language behaviour that a literal translation does not exercise.

Exact-excerpt verification does no normalization, translation or fuzzy matching in any language: a diacritized
sentence matches only itself, Arabic-Indic digits are digits (a bare quantity is bare in any script), bidi marks are
part of the text, and a number written as words is a result like any other, found only if the model declares it.
These families are Arabic-script data only (English has no counterpart), so they are the language-specific part of
the semantic-family count. Arabic here is test/source DATA."""

from __future__ import annotations

import re

from phase3b_gold_framework import family
from phase3b_gold_templates3 import mk

AR_MX = ("ar", "mixed")
TASHKEEL = re.compile("[ً-ْٰ]")
RLM = "‏"

DIACRITIZED = {
    "ar": "الهَدَفُ هُوَ التَّحَقُّقُ مِنْ أَنَّ الجِهَازَ يُبْقِي الرُّطُوبَةَ دَاخِلَ النِّطَاقِ المُسْتَهْدَفِ.",
    "mixed": "الهَدَفُ هُوَ التَّحَقُّقُ مِنْ أَنَّ الـ controller يُبْقِي soil moisture دَاخِلَ target band.",
}
BIDI = {
    "ar": f"تُقاس الدقة باستخدام {RLM}accuracy{RLM} على كل صينية في المختبر كل ساعة.",
    "mixed": f"تُقاس الدقة باستخدام {RLM}accuracy score{RLM} على كل tray في المختبر كل ساعة.",
}
INDIC_RESULT = {
    "ar": "النتيجة: أبقى الجهاز الرطوبة داخل النطاق ٩٧ بالمئة من الوقت.",
    "mixed": "النتيجة: أبقى الـ controller الرطوبة داخل band ٩٧ بالمئة من الوقت.",
}
WORD_RESULT = {
    "ar": "في النهاية بلغت الدقة ثمانية وتسعين بالمئة من الوقت.",
    "mixed": "في النهاية بلغت الـ accuracy ثمانية وتسعين بالمئة من الوقت.",
}
INDIC_SAMPLE = {"ar": "N = ٥٠٠.", "mixed": "N = ٥٠٠."}


@family("lang.arabic_diacritized_excerpt_is_matched_exactly", "arabic_script", AR_MX)
def _a1(lang: str) -> dict:
    sc, e = mk(lang)
    e.replace_doc("OBJECTIVE", DIACRITIZED[lang])
    sc.result("RES_POS")
    sc.expect(**{"x1__doc__OBJECTIVE": "EXPLICITLY_DOCUMENTED", "x1__posture": "WELL_SPECIFIED"})
    return sc.finish()


@family("lang.arabic_quote_without_diacritics_is_refused", "arabic_script", AR_MX)
def _a2(lang: str) -> dict:
    sc, e = mk(lang)
    e.replace_doc("OBJECTIVE", DIACRITIZED[lang])
    stripped = TASHKEEL.sub("", DIACRITIZED[lang])
    e.docs.pop("OBJECTIVE")
    e.missing.add("OBJECTIVE")
    e.raw_reqs = {"OBJECTIVE": {"excerpts": [stripped]}}
    sc.result("RES_POS")
    sc.expect(**{"x1__doc__OBJECTIVE": "NOT_DOCUMENTED_IN_BOUND_INPUT", "errors": ["EXACT_EXCERPT_MISMATCH"],
                 "x1__issues": ["OBJECTIVE_MISSING"], "x1__posture": "MAJOR_GAPS"})
    return sc.finish()


@family("lang.arabic_indic_digits_are_a_bare_quantity", "arabic_script", AR_MX)
def _a3(lang: str) -> dict:
    sc, e = mk(lang, "SCIENTIFIC_CONTROLLED_EXPERIMENT", fired={"SAMPLE_SIZE_RATIONALE": ["SAMPLED_POPULATION"]},
               missing=("SAMPLE_SIZE_RATIONALE",))
    bare = sc.say(INDIC_SAMPLE[lang])
    e.raw_reqs = {"SAMPLE_SIZE_RATIONALE": {"excerpts": [bare]}}
    sc.result("RES_POS")
    sc.flags["bare_n"] = True
    sc.expect(**{"x1__doc__SAMPLE_SIZE_RATIONALE": "NOT_DOCUMENTED_IN_BOUND_INPUT", "errors": ["PARTIAL_MODEL_OUTPUT"],
                 "x1__issues": ["REQUIRED_PROTOCOL_ELEMENT_MISSING"]})
    return sc.finish()


@family("lang.bidi_marks_are_part_of_the_excerpt", "arabic_script", AR_MX)
def _a4(lang: str) -> dict:
    sc, e = mk(lang)
    e.replace_doc("METRIC", BIDI[lang])
    sc.result("RES_POS")
    sc.expect(**{"x1__doc__METRIC": "EXPLICITLY_DOCUMENTED", "x1__posture": "WELL_SPECIFIED"})
    return sc.finish()


@family("lang.arabic_indic_result_digits_are_quarantined_and_inert", "arabic_script", AR_MX)
def _a5(lang: str) -> dict:
    sc, e = mk(lang)
    sc.result("RES_POS", text=INDIC_RESULT[lang])
    sc.expect(n_quar=1, quar_texts=[INDIC_RESULT[lang]], later_prompt_leak=False, **{"twin.result": True, "twin.result_quarantine": True})
    return sc.finish(twin="result", twin_data={"swap": {"٩٧": "٤١"}})


@family("lang.number_written_as_words_is_a_result_the_model_may_miss", "arabic_script", AR_MX)
def _a6(lang: str) -> dict:
    sc, e = mk(lang)
    sc.result("RES_POS", text=WORD_RESULT[lang], declare=False)
    sc.expect(n_quar=0)
    return sc.finish()


@family("lang.number_written_as_words_declared_is_quarantined", "arabic_script", AR_MX)
def _a7(lang: str) -> dict:
    sc, e = mk(lang)
    sc.result("RES_POS", text=WORD_RESULT[lang])
    sc.expect(n_quar=1, quar_texts=[WORD_RESULT[lang]], later_prompt_leak=False)
    return sc.finish()
