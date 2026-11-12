"""tagesschau.de business news (ressort=wirtschaft) that name a DAX, MDAX or SDAX company.

Source: Tagesschau API, documented at https://tagesschau.api.bund.dev. Terms: private, non-commercial use,
no publication, at most 60 requests per hour. Only title, time and link are kept as an event; the article
text stays on tagesschau.de.

download() walks back day by day (news?ressort=wirtschaft&date=YYMMDD, the API's own `nextPage` links) and
stores each raw page in data/raw_events/tagesschau/. It waits SPACING seconds between requests, so it never
exceeds 60 per hour, and never downloads a stored day again.
fetch() reads only the stored pages and needs no network.

Matching is by company name in title, topline, first sentence and the article's tags, with a hand-written
alias list: short names such as "Post", "Fuchs" or "Rational" are left out on purpose, they hit other things.
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from backend.fetcher import ROOT, Event

log = logging.getLogger(__name__)

RAW = ROOT / "data" / "raw_events" / "tagesschau"
API = "https://www.tagesschau.de/api2u/news/?ressort=wirtschaft&date={yymmdd}"
UA = "IssuerIntelligenceHub/0.1 (hackathon prototype; max 60 requests/hour)"
SPACING = 62  # seconds between requests: 58 per hour at most
FIRST_DAY, LAST_DAY = "2026-01-01", "2026-10-31"

# ISIN -> regex on the article text. Case-sensitive; word boundaries where a name is also a common word.
ALIASES: dict[str, str] = {
    "DE000A1EWWW0": r"\b[Aa]didas\b",  # ADS ADIDAS AG NA O.N.
    "NL0000235190": r"\bAirbus\b",  # AIR AIRBUS SE
    "DE0008404005": r"\bAllianz (SE|Versicherung|Group)\b|\bVersicherer Allianz\b|\bAllianz-(Konzern|Chef|Chefin|Versicherung|Aktie|Gruppe)\b",  # ALV ALLIANZ SE NA O.N.
    "DE000BASF111": r"\bBASF\b",  # BAS BASF SE NA O.N.
    "DE000BAY0017": r"\bBayer\b(?! ?[Ll]everkusen)",  # BAYN BAYER AG NA O.N.
    "DE0005200000": r"\bBeiersdorf\b|\bNivea\b",  # BEI BEIERSDORF AG O.N.
    "DE0005190003": r"\bBMW\b",  # BMW BAY.MOTOREN WERKE AG ST
    "DE000A1DAHH0": r"\bBrenntag\b",  # BNR BRENNTAG SE NA O.N.
    "DE0005439004": r"\bContinental\b",  # CON CONTINENTAL AG O.N.
    "DE0005810055": r"\bDeutsche Börse\b|\bDeutschen Börse\b",  # DB1 DEUTSCHE BOERSE NA O.N.
    "DE0005140008": r"\bDeutsche Bank\b|\bDeutschen Bank\b",  # DBK DEUTSCHE BANK AG NA O.N.
    "DE0005552004": r"\bDHL\b|\bDeutsche Post\b|\bDeutschen Post\b",  # DHL DHL AG
    "DE0005557508": r"\bTelekom\b",  # DTE DT.TELEKOM AG NA
    "DE000DTR0CK8": r"\bDaimler Truck\b",  # DTG DAIMLER TRUCK HLDG NA ON
    "DE000ENER6Y0": r"\bSiemens Energy\b",  # ENR SIEMENS ENERGY AG NA O.N.
    "DE000ENAG999": r"\bE\.ON\b|\bEon\b",  # EOAN E.ON SE NA O.N.
    "DE0005785802": r"\bFresenius Medical Care\b|\bFMC\b",  # FME FRESEN.MED.CARE AG INH ON
    "DE000FRE5EN2": r"\bFresenius\b(?! Medical)",  # FRE FRESENIUS SE+CO.KGAA O.N.
    "DE0006602006": r"\bGEA\b",  # G1A GEA GROUP AG
    "DE000A12DM80": r"\bScout24\b|\bImmoscout",  # G24 SCOUT24 SE NA O.N.
    "DE0006047004": r"\bHeidelberg Materials\b",  # HEI HEIDELBERG MATERIALS O.N.
    "DE0006048432": r"\bHenkel\b",  # HEN3 HENKEL AG+CO.KGAA VZO
    "DE0008402215": r"\bHannover Rück\b|\bHannover Re\b",  # HNR1 HANNOVER RUECK SE NA O.N.
    "DE0006070006": r"\bHochtief\b",  # HOT HOCHTIEF AG
    "DE0006231004": r"\bInfineon\b",  # IFX INFINEON TECH.AG NA O.N.
    "DE0007100000": r"\bMercedes\b",  # MBG MERCEDES-BENZ GRP NA O.N.
    "DE0006599905": r"\bMerck\b(?! Sharp| & Co| and Co|, Sharp)",  # MRK MERCK KGAA O.N.
    "DE000A0D9PT0": r"\bMTU\b",  # MTX MTU AERO ENGINES NA O.N.
    "DE0008430026": r"\bMünchener Rück\b|\bMunich Re\b",  # MUV2 MUENCH.RUECKVERS. NA O.N.
    "NL0015002SN0": r"\bQiagen\b",  # QIA QIAGEN NV         EO -,01
    "DE0007030009": r"\bRheinmetall\b",  # RHM RHEINMETALL AG
    "DE0007037129": r"\bRWE\b",  # RWE RWE AG   INH O.N.
    "DE0007164600": r"\bSAP\b",  # SAP SAP SE O.N.
    "DE000SHL1006": r"\bSiemens Healthineers\b|\bHealthineers\b",  # SHL SIEMENS HEALTH.AG NA O.N.
    "DE0007236101": r"\bSiemens\b(?! Energy| Healthineers| Gamesa)",  # SIE SIEMENS AG  NA O.N.
    "DE000SYM9999": r"\bSymrise\b",  # SY1 SYMRISE AG INH. O.N.
    "DE000A1ML7J1": r"\bVonovia\b",  # VNA VONOVIA SE NA O.N.
    "DE0007664039": r"\bVolkswagen\b|\bVW\b",  # VOW3 VOLKSWAGEN AG VZO O.N.
    "DE000ZAL1111": r"\bZalando\b",  # ZAL ZALANDO SE
    "DE000TRAT0N7": r"\bTraton\b",  # 8TRA TRATON SE   INH O.N.
    "DE000A2LQ884": r"\bAuto1\b",  # AG1 AUTO1 GROUP SE  INH O.N.
    "DE000A0WMPJ6": r"\bAixtron\b",  # AIXA AIXTRON SE NA O.N.
    "DE000AUM0V10": r"\bAumovio\b",  # AMV0 AUMOVIO SE NA O.N.
    "LU1673108939": r"\bAroundtown\b",  # AT1 AROUNDTOWN EO-,01
    "DE0005158703": r"\bBechtle\b",  # BC8 BECHTLE AG O.N.
    "DE0006305006": r"\bDeutz\b",  # DEZ DEUTZ AG O.N.
    "DE000A2E4K43": r"\bDelivery Hero\b",  # DHER DELIVERY HERO SE NA O.N.
    "DE0005677108": r"\bElmos\b",  # ELG ELMOS SEMICOND. INH O.N.
    "DE0005470306": r"\bEventim\b",  # EVD CTS EVENTIM KGAA
    "DE000EVNK013": r"\bEvonik\b",  # EVK EVONIK INDUSTRIES NA O.N.
    "DE000A0Z2ZZ5": r"\b[Ff]reenet\b",  # FNTN FREENET AG NA O.N.
    "DE000A3E5D64": r"\bFuchs Petrolub\b|\bSchmierstoffhersteller Fuchs\b",  # FPE3 FUCHS SE  VZO NA O.N.
    "DE0005773303": r"\bFraport\b",  # FRA FRAPORT AG FFM.AIRPORT
    "DE000FTG1111": r"\b[Ff]latex",  # FTK FLATEXDEGIRO SE NA O.N.
    "DE0005909006": r"\bBilfinger\b",  # GBF BILFINGER SE O.N.
    "DE000HAG0005": r"\bHensoldt\b",  # HAG HENSOLDT AG INH O.N.
    "DE000A13SX22": r"\bHella\b",  # HLE HELLA GMBH+CO. KGAA O.N.
    "DE000A3E00M1": r"\bIonos\b|\bIONOS\b",  # IOS IONOS GROUP SE NA O.N.
    "DE000A2NB601": r"\bJenoptik\b",  # JEN JENOPTIK AG  NA O.N.
    "DE000KBX1006": r"\bKnorr-Bremse\b",  # KBX KNORR-BREMSE AG  INH O.N.
    "DE000KGX8881": r"\bKion\b|\bKION\b",  # KGX KION GROUP AG
    "DE0006335003": r"\bKrones\b",  # KRN KRONES AG O.N.
    "DE000LEG1110": r"\bLEG Immobilien\b",  # LEG LEG IMMOBILIEN SE NA O.N.
    "DE0008232125": r"\bLufthansa\b",  # LHA LUFTHANSA AG VNA O.N.
    "DE0005470405": r"\bLanxess\b",  # LXS LANXESS AG
    "DE0006766504": r"\bAurubis\b",  # NDA AURUBIS AG
    "DE000A0D6554": r"\bNordex\b",  # NDX1 NORDEX SE O.N.
    "DE0006452907": r"\bNemetschek\b",  # NEM NEMETSCHEK SE O.N.
    "DE000PAG9113": r"\bPorsche\b(?! SE| Holding| Automobil Holding)",  # P911 DR.ING.H.C.F.PORSCHE VZO
    "DE000PAH0038": r"\bPorsche SE\b|\bPorsche Automobil Holding\b",  # PAH3 PORSCHE AUTOM.HLDG VZO
    "DE0006969603": r"\bPuma\b",  # PUM PUMA SE
    "DE000RENK730": r"\bRenk\b",  # R3NK RENK GROUP AG INH O.N.
    "DE0007010803": r"\bRational AG\b",  # RAA RATIONAL AG
    "LU0061462528": r"\bRTL\b",  # RRTL RTL GROUP
    "DE0007493991": r"\bStröer\b",  # SAX STROEER SE + CO. KGAA
    "DE000KSAG888": r"\bK\+S\b",  # SDF K+S AG NA O.N.
    "DE000SHA0100": r"\bSchaeffler\b",  # SHA0 SCHAEFFLER AG NA O.N.
    "DE000A1K0235": r"\bSüss Micro[Tt]ec\b|\bSUSS MicroTec\b",  # SMHN SUSS MICROTEC SE NA O.N.
    "DE0007165631": r"\bSartorius\b",  # SRT3 SARTORIUS AG VZO O.N.
    "DE0006202005": r"\bSalzgitter\b",  # SZG SALZGITTER AG O.N.
    "DE0008303504": r"\bTAG Immobilien\b",  # TEG TAG IMMOBILIEN AG
    "DE0007500001": r"\b[Tt]hyssen[Kk]rupp\b(?! Marine)",  # TKA THYSSENKRUPP AG O.N.
    "DE000TKMS001": r"\bTKMS\b|\b[Tt]hyssen[Kk]rupp Marine Systems\b",  # TKMS TKMS AG + CO. KGAA O.N.
    "DE000TLX1005": r"\bTalanx\b",  # TLX TALANX AG NA O.N.
    "DE000TUAG505": r"\bTUI\b",  # TUI1 TUI AG NA O.N.
    "DE0005089031": r"\bUnited Internet\b",  # UTDI UTD.INTERNET AG NA
    "DE000WAF3001": r"\bSiltronic\b",  # WAF SILTRONIC AG NA O.N.
    "DE000WCH8881": r"\bWacker Chemie\b",  # WCH WACKER CHEMIE        O.N.
    "AT100ASTA001": r"\bAsta Energy\b|\bASTA Energy\b",  # 1AST ASTA ENERGY SOLUTIONS AG
    "DE000A3ENQ51": r"\bSchott Pharma\b",  # 1SXP SCHOTT PHARMA INH O.N.
    "DE0005545503": r"\b1&1\b",  # 1U1 1+1 AG  INH O.N.
    "DE000A41YHG1": r"\bAlzchem\b|\bAlzChem\b",  # ACT0 ALZCHEM GROUP AG NA O.N.
    "DE0005103006": r"\bAdtran\b",  # ADV ADTRAN NETW.SE INH O.N.
    "DE0005313704": r"\b(Carl )?Zeiss Meditec\b",  # AFX CARL ZEISS MEDITEC AG
    "DE0005104400": r"\bAtoss\b|\bATOSS\b",  # AOF ATOSS SOFTWARE SE INH O.N
    "LU1704650164": r"\bBefesa\b",  # BFSA BEFESA S.A. ORD. O.N.
    "DE000A1PHFF7": r"\bHugo Boss\b|\bHUGO BOSS\b",  # BOSS HUGO BOSS AG NA O.N.
    "DE0005102008": r"\bBasler AG\b",  # BSL BASLER AG O.N.
    "DE0005419105": r"\bCancom\b",  # COK CANCOM SE O.N.
    "DE0005403901": r"\bCewe\b|\bCEWE\b",  # CWC CEWE STIFT.KGAA  O.N.
    "DE000A1TNUT7": r"\bDeutsche Beteiligungs",  # DBAN DT.BETEILIG.AG   NA O.N.
    "DE0007480204": r"\bDeutsche Euro[Ss]hop\b",  # DEQ DEUTSCHE EUROSHOP NA O.N.
    "DE000A2GS5D8": r"\bDermapharm\b",  # DMP DERMAPHARM HLDG INH O.N.
    "DE000BEAU1Y4": r"\bDouglas\b",  # DOU DOUGLAS AG  NA O.N.
    "DE0005550636": r"\bDräger\b",  # DRW3 DRAEGERWERK VZO O.N.
    "DE0005565204": r"\bDürr\b",  # DUE DUERR AG O.N.
    "DE000A40ESU3": r"\bEinhell\b",  # EIN EINHELL GERMANY VZO O.N.
    "DE0005313506": r"\bEnergiekontor\b",  # EKT ENERGIEKONTOR O.N.
    "DE0005659700": r"\bEckert ?(&|\+|und) ?Ziegler\b",  # EUZ ECKERT+ZIEGLER  INH O.N.
    "DE0005664809": r"\bEvotec\b",  # EVT EVOTEC SE  INH O.N.
    "DE0007568578": r"\bSFC Energy\b",  # F3C SFC ENERGY AG
    "DE0005772206": r"\bFielmann\b",  # FIE FIELMANN GROUP AG O.N.
    "DE0005800601": r"\bGFT Technologies\b",  # GFT GFT TECHNOLOGIES SE
    "DE000A161N30": r"\bGrenke\b",  # GLJ GRENKE AG NA O.N.
    "LU0775917882": r"\bGrand City\b",  # GYC GRAND CITY PROPERT.EO-,10
    "DE000A3H2333": r"\bHamborner\b",  # HABA HAMBORNER REIT AG NA O.N.
    "DE0006083405": r"\bHornbach\b",  # HBH HORNBACH HOLD.ST O.N.
    "DE0007314007": r"\bHeidelberger Druck",  # HDD HEIDELBERG.DRUCKMA.O.N.
    "DE000A161408": r"\bHello[Ff]resh\b",  # HFG HELLOFRESH SE  INH O.N.
    "DE0005493365": r"\bHypoport\b",  # HYQ HYPOPORT SE  NA O.N.
    "DE000A1MMCC8": r"\bMedios\b",  # ILM1 MEDIOS AG  O.N.
    "DE0006200108": r"\bIndus Holding\b",  # INH INDUS HOLDING AG
    "DE000JST4000": r"\bJost Werke\b",  # JST JOST WERKE SE INH. O.N.
    "DE0006219934": r"\bJungheinrich\b",  # JUN3 JUNGHEINRICH AG O.N.VZO
    "DE0006292030": r"\bKSB\b",  # KSB3 KSB SE+CO.KGAA VZO O.N.
    "AT0000A0E9W5": r"\bKontron\b",  # KTN KONTRON AG O.N
    "DE0007074007": r"\bKWS Saat\b|\bKWS\b",  # KWS KWS SAAT KGAA  INH O.N.
    "DE0006450000": r"\bLPKF\b",  # LPK LPKF LASER+ELECTR.INH ON
    "DE0006569908": r"\bMLP\b",  # MLP MLP SE  INH. O.N.
    "DE000A2NB650": r"\bMutares\b",  # MUX MUTARES KGAA  NA O.N.
    "DE000A1H8BV3": r"\bNorma Group\b",  # NOEJ NORMA GROUP SE NA O.N.
    "DE000BCK2223": r"\bOttobock\b",  # OBCK OTTOBOCK SE+CO.KGAA  O.N.
    "DE0005936124": r"\bOHB\b",  # OHB OHB SE   O.N.
    "DE000PAT1AG3": r"\bPatrizia\b",  # PAT PATRIZIA SE NA O.N.
    "DE0006223407": r"\bProCredit\b",  # PCZ PROCREDIT HLDG AG NA EO 5
    "DE000A0JBPG2": r"\bPNE\b",  # PNE3 PNE AG  NA O.N.
    "NL0012044747": r"\bRedcare\b|\bShop Apotheke\b",  # RDC REDCARE PHARMACY INH.
    "DE000A0DJ6J9": r"\bSMA Solar\b",  # S92 SMA SOLAR TECHNOL.AG
    "DE000SAFH001": r"\bSAF-Holland\b",  # SFQ SAF-HOLLAND SE  INH EO 1
    "DE0007235301": r"\bSGL Carbon\b",  # SGL SGL CARBON SE O.N.
    "DE0007231326": r"\bSixt\b",  # SIX2 SIXT SE ST O.N.
    "BG1100003166": r"\bShelly\b",  # SLYG SHELLY GROUP PLC     EO 1
    "DE000SPG1003": r"\bSpringer Nature\b",  # SPG SPRINGER NATURE INH O.N.
    "DE000STAB1L8": r"\bStabilus\b",  # STM STABILUS SE INH. O.N.
    "DE0007297004": r"\bSüdzucker\b",  # SZU SUEDZUCKER AG  O.N.
    "DE000A2YN900": r"\bTeam[Vv]iewer\b",  # TMV TEAMVIEWER SE  INH O.N.
    "LU2333563281": r"\bTonies\b",  # TNIE TONIES SE            EO 1
    "DE0007461006": r"\bPVA Te[Pp]la\b",  # TPE PVA TEPLA AG O.N.
    "DE000VNC0014": r"\bVincorion\b|\bVINCORION\b",  # V1NC VINCORION SE INH O.N.
    "DE000A0JL9W6": r"\bVerbio\b",  # VBK VERBIO SE INH O.N.
    "DE000A255F11": r"\bFriedrich Vorwerk\b",  # VH2 FR.VORWERK GRP SE INH ON
    "DE0007667107": r"\bVossloh\b",  # VOS VOSSLOH AG O.N.
    "DE000WACK012": r"\bWacker Neuson\b",  # WAC WACKER NEUSON SE NA O.N.
    "DE0007276503": r"\b[Ss]ecunet\b",  # YSN SECUNET SECURITY AG O.N.
    "DE000CBK1001": r"\bCommerzbank\b",  # CBK Commerzbank
    "DE000DWS1007": r"\bDWS\b",  # DWS DWS Group
    "DE0008019001": r"\bPfandbriefbank\b|\bpbb\b",  # PBB Deutsche Pfandbriefbank
}


def _yymmdd(day: str) -> str:
    return day[2:4] + day[5:7] + day[8:10]


def download(max_requests: int = 1000) -> int:
    """Store every missing day from LAST_DAY back to FIRST_DAY. Returns the number of requests made."""
    RAW.mkdir(parents=True, exist_ok=True)
    made = 0
    day = datetime.fromisoformat(LAST_DAY).date()
    first = datetime.fromisoformat(FIRST_DAY).date()
    from datetime import timedelta

    while day >= first and made < max_requests:
        key = _yymmdd(day.isoformat())
        path = RAW / f"wirtschaft_{key}.json"
        if not path.exists():
            if made:
                time.sleep(SPACING)
            req = urllib.request.Request(API.format(yymmdd=key), headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                path.write_text(r.read().decode())
            made += 1
            log.info("tagesschau %s stored (%d requests this run)", day, made)
        day -= timedelta(days=1)
    return made


def companies_in(item: dict, compiled: dict[str, re.Pattern[str]], universe: set[str]) -> list[str]:
    text = " ".join(
        [item.get("title") or "", item.get("topline") or "", item.get("firstSentence") or ""]
        + [t.get("tag", "") for t in item.get("tags") or []]
    )
    return [isin for isin, rx in compiled.items() if isin in universe and rx.search(text)]


def fetch(universe: set[str] | None = None) -> list[Event]:
    """Events from the stored pages only. `universe`: ISINs to keep (default: every ISIN in ALIASES)."""
    compiled = {isin: re.compile(p) for isin, p in ALIASES.items()}
    universe = universe or set(ALIASES)
    seen: set[tuple[str, str]] = set()
    events: list[Event] = []
    for path in sorted(RAW.glob("wirtschaft_*.json")):
        try:
            items = json.loads(path.read_text()).get("news", [])
        except json.JSONDecodeError:
            log.warning("tagesschau: unreadable %s", path.name)
            continue
        for it in items:
            url = it.get("shareURL") or it.get("detailsweb")
            if not url or not it.get("date") or not (FIRST_DAY <= it["date"][:10] <= LAST_DAY):
                continue
            title = it.get("title") or ""
            if it.get("topline"):
                title = f"{it['topline']}: {title}"
            for isin in companies_in(it, compiled, universe):
                if (isin, url) in seen:
                    continue
                seen.add((isin, url))
                events.append(Event(
                    isin=isin, type="news", title=title,
                    published_at_utc=datetime.fromisoformat(it["date"]),
                    source="tagesschau", url=url, confidence=0.8,
                ))
    log.info("tagesschau: %d company mentions from %d stored days", len(events), len(list(RAW.glob("wirtschaft_*.json"))))
    return events


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    print(download(), "requests made")
