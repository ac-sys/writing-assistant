"""US -> British spelling for common words (used when 'Keep British English' is on)."""
import re

_WORDS = {
    "color": "colour", "colors": "colours", "colored": "coloured", "behavior": "behaviour", "behaviors": "behaviours",
    "behavioral": "behavioural", "favor": "favour", "favors": "favours", "favorable": "favourable", "favorite": "favourite",
    "honor": "honour", "labor": "labour", "neighbor": "neighbour", "neighbors": "neighbours", "neighborhood": "neighbourhood",
    "humor": "humour", "rumor": "rumour", "endeavor": "endeavour", "endeavors": "endeavours", "harbor": "harbour",
    "center": "centre", "centers": "centres", "centered": "centred", "theater": "theatre", "fiber": "fibre",
    "liter": "litre", "liters": "litres", "kilometer": "kilometre", "kilometers": "kilometres",
    "defense": "defence", "offense": "offence", "catalog": "catalogue", "dialog": "dialogue", "analog": "analogue",
    "traveled": "travelled", "traveling": "travelling", "traveler": "traveller", "travelers": "travellers",
    "modeling": "modelling", "modeled": "modelled", "labeled": "labelled", "labeling": "labelling",
    "canceled": "cancelled", "canceling": "cancelling", "counseling": "counselling", "counselor": "counsellor",
    "fulfill": "fulfil", "fulfillment": "fulfilment", "enroll": "enrol", "enrollment": "enrolment", "skillful": "skilful",
    "aging": "ageing", "gray": "grey", "jewelry": "jewellery", "mold": "mould", "plow": "plough",
    "analyze": "analyse", "analyzed": "analysed", "analyzes": "analyses", "analyzing": "analysing",
    "paralyze": "paralyse", "catalyze": "catalyse", "program's": "programme's", "practicing": "practising",
    "license": "licence", "judgment": "judgement", "acknowledgment": "acknowledgement", "pediatric": "paediatric",
    "anemia": "anaemia", "maneuver": "manoeuvre", "estrogen": "oestrogen", "esophagus": "oesophagus",
}
_IZE_STEMS = ("organi", "reali", "recogni", "emphasi", "priori", "summari", "minimi", "maximi", "optimi", "characteri",
              "categori", "critici", "speciali", "generali", "standardi", "utili", "visuali", "mobili", "moderni",
              "apologi", "authori", "capitali", "centrali", "civili", "customi", "digiti", "finali", "globali",
              "harmoni", "hospitali", "industriali", "initiali", "internationali", "itemi", "legali", "localis",
              "memori", "monetiz", "normali", "personali", "polari", "publici", "randomi", "revolutioni",
              "scrutini", "sociali", "stabili", "symboli", "synchroni", "theori", "urbani", "verbali", "conceptuali",
              "contextuali", "operationali", "democrati", "economi", "familiari", "hypothesi", "jeopardi", "patroni",
              "sensiti", "subsidi", "sympathi", "vandali", "galvani", "energi", "decentrali", "commerciali", "criminali")


def _case(src, rep):
    if src.isupper():
        return rep.upper()
    if src[:1].isupper():
        return rep[:1].upper() + rep[1:]
    return rep


def to_british(text):
    rx = re.compile(r"\b(" + "|".join(sorted(map(re.escape, _WORDS), key=len, reverse=True)) + r")\b", re.IGNORECASE)
    text = rx.sub(lambda m: _case(m.group(0), _WORDS[m.group(0).lower()]), text)

    def ize(m):
        w = m.group(0)
        low = w.lower()
        if any(low.startswith(s) for s in _IZE_STEMS):
            return w[:m.start(1) - m.start()] + _case(m.group(1), m.group(1).replace("z", "s").replace("Z", "S"))
        return w
    text = re.sub(r"\b[A-Za-z]+?(iz(?:e|es|ed|ing|ation|ations|er|ers))\b", ize, text)
    return text
