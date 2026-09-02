"""
Translation engine for the Layman's Translator.

Two directions:
  to_plain(text)  Econ  -> Plain   replace jargon with everyday phrases and
                                    explain every term that was found
  to_econ(text)   Plain -> Econ    replace everyday phrases with the proper
                                    economics term and explain each one

Pure Python, no dependencies, works offline.
"""

import re
from dataclasses import dataclass, field

from glossary import TERMS, SIMPLIFICATIONS, Term


# ---------------------------------------------------------------- helpers

def _pattern_for(phrase: str) -> str:
    """Regex for a phrase: case-insensitive, word-bounded, flexible spacing/hyphens,
    optional simple plural on the last word."""
    words = re.split(r"[\s\-]+", phrase.strip())
    parts = [re.escape(w) for w in words]
    body = r"[\s\-]+".join(parts)
    # allow plural on the final word unless it already ends in 's' or is a symbol
    if words[-1][-1:].isalpha() and not words[-1].endswith("s"):
        body += r"(?:e?s)?"
    # \b does not work next to symbols like '&' or '%'; use lookarounds
    return r"(?<![\w])" + body + r"(?![\w])"


def _match_case(replacement: str, matched: str, at_start: bool) -> str:
    """Capitalise the replacement only at the start of a sentence."""
    if at_start and matched[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def _no_article(phrase: str) -> str:
    """Drop a leading 'a'/'an' so the phrase drops into any sentence; _tidy fixes articles."""
    return re.sub(r"^(?:a|an) ", "", phrase, flags=re.I)


def _pluralize(phrase: str) -> str:
    """Rough plural of a noun phrase: drop a leading article, pluralise the last word."""
    words = phrase.split()
    if words and words[0].lower() in ("a", "an"):
        words = words[1:]
    if not words:
        return phrase
    last = words[-1]
    if last.endswith("s") or not last[-1:].isalpha():
        pass
    elif last.endswith("y") and last[-2:-1].lower() not in "aeiou":
        last = last[:-1] + "ies"
    elif last.endswith(("x", "ch", "sh", "z")):
        last += "es"
    else:
        last += "s"
    words[-1] = last
    return " ".join(words)


def _is_plural_form(matched: str, phrase: str, term_name: str) -> bool:
    """Was the matched text a plural of the phrase (or the phrase itself a plural alias)?"""
    norm = re.sub(r"[\s\-]+", " ", matched.lower().strip())
    if norm != phrase.lower():
        return True                      # the optional (e?s) tail was used
    t = term_name.lower().split()[-1]
    ph = phrase.lower().split()[-1]
    if ph == t:
        return False
    return ph in (t + "s", t + "es") or (t.endswith("y") and ph == t[:-1] + "ies")


def hard_words(text: str) -> int:
    """Count words of three or more syllables (the Gunning fog 'complex word')."""
    return sum(1 for w in re.findall(r"[A-Za-z][A-Za-z'\-]*", text) if _syllables(w) >= 3)


def _syllables(word: str) -> int:
    word = word.lower().strip("'\"")
    if not word:
        return 0
    if len(word) <= 3:
        return 1
    word = re.sub(r"(?:[^laeiouy]es|ed|[^laeiouy]e)$", "", word)
    word = re.sub(r"^y", "", word)
    return max(1, len(re.findall(r"[aeiouy]{1,2}", word)))


def reading_grade(text: str) -> float | None:
    """Flesch-Kincaid grade level. Returns None when there is too little text."""
    words = re.findall(r"[A-Za-z][A-Za-z'\-]*", text)
    if len(words) < 3:
        return None
    sentences = max(1, len(re.findall(r"[.!?]+(?:\s|$)", text)) or 1)
    syl = sum(_syllables(w) for w in words)
    grade = 0.39 * (len(words) / sentences) + 11.8 * (syl / len(words)) - 15.59
    return round(max(0.0, grade), 1)


def grade_label(grade: float | None) -> str:
    if grade is None:
        return "n/a"
    if grade < 6:
        return f"grade {grade:g} (very easy)"
    if grade < 9:
        return f"grade {grade:g} (plain)"
    if grade < 13:
        return f"grade {grade:g} (high school)"
    if grade < 16:
        return f"grade {grade:g} (college)"
    return f"grade {grade:g} (academic)"


# ------------------------------------------------------- reverse phrasing
# Everyday ways of saying things, mapped to the economics term. Only the
# `plain` phrase of each glossary entry is matched automatically; these add
# the many other ways people say the same thing.
REVERSE_PHRASES = {
    "prices going up": "inflation",
    "prices are going up": "inflation",
    "prices keep going up": "inflation",
    "prices rising": "inflation",
    "prices are rising": "inflation",
    "everything is getting more expensive": "inflation",
    "things getting more expensive": "inflation",
    "the cost of everything going up": "inflation",
    "money buys less": "inflation",
    "prices going down": "deflation",
    "prices are falling": "deflation",
    "prices dropping": "deflation",
    "the economy is shrinking": "recession",
    "the economy shrinks": "recession",
    "the economy is slowing down": "slowdown",
    "a bad economy": "recession",
    "the economy is growing": "economic growth",
    "the economy is getting bigger": "economic growth",
    "the economy grows": "economic growth",
    "the economy is doing well": "economic expansion",
    "the economy is booming": "economic boom",
    "everything the country makes": "gross domestic product",
    "everything a country produces": "gross domestic product",
    "the size of the economy": "gross domestic product",
    "people who can't find work": "the unemployed",
    "people who cannot find work": "the unemployed",
    "people can't find jobs": "unemployment is high",
    "people cannot find jobs": "unemployment is high",
    "can't find a job": "is unemployed",
    "cannot find a job": "is unemployed",
    "out of work": "unemployed",
    "lost their jobs": "became unemployed",
    "losing their jobs": "becoming unemployed",
    "nobody can find workers": "the labor market is tight",
    "companies can't find workers": "the labor market is tight",
    "the cost of borrowing": "the interest rate",
    "cost of borrowing money": "interest rate",
    "how much it costs to borrow": "the interest rate",
    "borrowing gets more expensive": "interest rates rise",
    "borrowing gets cheaper": "interest rates fall",
    "made borrowing more expensive": "raised interest rates",
    "made borrowing cheaper": "cut interest rates",
    "raised rates": "raised interest rates",
    "cut rates": "cut interest rates",
    "the fed raised rates": "the Federal Reserve tightened monetary policy",
    "the fed cut rates": "the Federal Reserve eased monetary policy",
    "printing money": "expanding the money supply",
    "print money": "expand the money supply",
    "printed money": "expanded the money supply",
    "the government spends more than it takes in": "the government runs a budget deficit",
    "the government spends more than it collects": "the government runs a budget deficit",
    "spending more than it takes in": "running a deficit",
    "spending more than it collects": "running a deficit",
    "spending more than it earns": "running a deficit",
    "the government takes in more than it spends": "the government runs a budget surplus",
    "what the government owes": "the national debt",
    "everything the government owes": "the national debt",
    "the government's credit card balance": "the national debt",
    "government spending cuts": "austerity",
    "cutting government spending": "fiscal consolidation",
    "government handouts": "transfer payments",
    "government checks": "fiscal stimulus",
    "the government sending people money": "fiscal stimulus",
    "government help for the economy": "fiscal stimulus",
    "a tax on imports": "a tariff",
    "tax on imports": "tariff",
    "taxes on imports": "tariffs",
    "taxes on foreign goods": "tariffs",
    "tax on foreign goods": "tariff",
    "stuff we buy from other countries": "imports",
    "things we buy from abroad": "imports",
    "stuff we sell to other countries": "exports",
    "things we sell abroad": "exports",
    "buying more from abroad than we sell": "running a trade deficit",
    "we buy more than we sell abroad": "we run a trade deficit",
    "a home loan": "a mortgage",
    "home loan": "mortgage",
    "home loans": "mortgages",
    "house loan": "mortgage",
    "the bank took their house": "the home was foreclosed",
    "losing their house to the bank": "foreclosure",
    "owe more than the house is worth": "are in negative equity",
    "owe more than their house is worth": "are in negative equity",
    "using borrowed money": "using leverage",
    "borrowed money": "credit",
    "borrowing money": "taking on debt",
    "couldn't pay back the loan": "defaulted on the loan",
    "could not pay back the loan": "defaulted on the loan",
    "didn't pay back": "defaulted on",
    "can't pay their debts": "are insolvent",
    "cannot pay their debts": "are insolvent",
    "owes more than it has": "is insolvent",
    "everyone rushing to take their money out of the bank": "a bank run",
    "everyone pulling their money out of the bank": "a bank run",
    "the government rescued the bank": "the bank was bailed out",
    "rescued with taxpayer money": "bailed out",
    "an iou that pays interest": "a bond",
    "a loan to the government": "a government bond",
    "lending money to the government": "buying government bonds",
    "what you earn on an investment": "the yield",
    "what you get back": "the return",
    "not putting all your eggs in one basket": "diversification",
    "spreading your money around": "diversifying",
    "prices swinging wildly": "high volatility",
    "prices swing a lot": "prices are volatile",
    "stocks going up for a long time": "a bull market",
    "stocks going down for a long time": "a bear market",
    "stocks are up": "equities are rallying",
    "stocks are down": "equities are falling",
    "the stock market crashed": "equity markets crashed",
    "prices way higher than things are worth": "a bubble",
    "prices are way too high": "the market is overvalued",
    "the price is too high for what it is": "it is overvalued",
    "a piece of a company": "equity",
    "a share of a company": "a share of equity",
    "own part of a company": "hold equity",
    "the company's payout to owners": "the dividend",
    "what you give up": "the opportunity cost",
    "what you gave up": "the opportunity cost",
    "what you miss out on": "the opportunity cost",
    "the next best thing you could have done": "the opportunity cost",
    "not enough to go around": "scarcity",
    "there isn't enough": "there is a shortage",
    "there is not enough": "there is a shortage",
    "too much of it": "a glut",
    "way more than people want": "oversupply",
    "each extra one helps less": "diminishing returns",
    "each extra bit helps less": "diminishing returns",
    "cheaper to make when you make a lot": "economies of scale",
    "cheaper per unit as you make more": "economies of scale",
    "getting cheaper the more you make": "economies of scale",
    "one company controls everything": "a monopoly",
    "only one seller": "a monopoly",
    "only one company sells it": "it is a monopoly",
    "a few big companies control it": "an oligopoly",
    "only one buyer": "a monopsony",
    "only one employer in town": "a monopsony",
    "companies secretly agreeing on prices": "a cartel",
    "companies fixing prices together": "collusion",
    "rigging prices": "price fixing",
    "no government interference": "laissez-faire",
    "the government stays out of it": "a free market",
    "the government sets the price": "price controls",
    "a cap on prices": "a price ceiling",
    "the highest price allowed": "a price ceiling",
    "the lowest price allowed": "a price floor",
    "the lowest legal pay": "the minimum wage",
    "the least you can legally be paid": "the minimum wage",
    "how much stuff people want to buy": "demand",
    "how much people want to buy": "demand",
    "how much people want it": "demand",
    "how much is available to buy": "supply",
    "how much is for sale": "supply",
    "how much there is": "supply",
    "when people want more than there is": "excess demand",
    "when there's more than people want": "excess supply",
    "the price where buyers and sellers agree": "the equilibrium price",
    "the price settles": "the market reaches equilibrium",
    "people keep buying it no matter the price": "demand is inelastic",
    "people buy it no matter what it costs": "demand is inelastic",
    "people stop buying when the price goes up": "demand is elastic",
    "people buy less when the price goes up": "demand is elastic",
    "side effects on other people": "externalities",
    "a side effect on other people": "an externality",
    "side effect on people not involved": "externality",
    "pollution that hurts the neighbors": "a negative externality",
    "things everyone can use for free": "public goods",
    "everyone uses it and no one pays": "it is a public good",
    "taking risks because someone else pays": "moral hazard",
    "taking risks because you're covered": "moral hazard",
    "one side knows more than the other": "asymmetric information",
    "the seller knows more than the buyer": "asymmetric information",
    "buying cheap here and selling dear there": "arbitrage",
    "buy low in one place and sell high in another": "arbitrage",
    "betting prices will go up": "speculating",
    "betting on prices": "speculation",
    "getting rich by gaming the system": "rent-seeking",
    "lobbying for special treatment": "rent-seeking",
    "everyone overusing something shared": "the tragedy of the commons",
    "the rich get richer and the poor get poorer": "inequality is widening",
    "the gap between rich and poor": "inequality",
    "rich and poor gap": "inequality",
    "the middle income": "the median income",
    "the typical income": "the median income",
    "how much your money buys": "purchasing power",
    "how much your money actually buys": "purchasing power",
    "your money doesn't go as far": "purchasing power has fallen",
    "your money does not go as far": "purchasing power has fallen",
    "after taking out rising prices": "in real terms",
    "after adjusting for rising prices": "in real terms",
    "adjusted for rising prices": "in real terms",
    "the raw number": "the nominal figure",
    "take-home pay": "disposable income",
    "take home pay": "disposable income",
    "spending money": "discretionary income",
    "pay going up": "wage growth",
    "wages going up": "wage growth",
    "a pay raise": "wage growth",
    "pay rises": "wages increase",
    "wages and prices chasing each other": "a wage-price spiral",
    "workers and shops both raising prices": "a wage-price spiral",
    "what people spend": "consumption",
    "people spending money": "consumer spending",
    "people are spending less": "consumption is falling",
    "people are spending more": "consumption is rising",
    "people feel good about the economy": "consumer confidence is high",
    "people feel bad about the economy": "consumer confidence is low",
    "people are worried about money": "consumer confidence is low",
    "people feel richer": "the wealth effect",
    "feel richer so spend more": "the wealth effect",
    "buying machines and buildings": "capital investment",
    "spending on machines and buildings": "capital investment",
    "tools and machines and buildings": "capital",
    "tools and machines": "capital",
    "people's skills and training": "human capital",
    "skills and education": "human capital",
    "workers": "labor",
    "how much gets done per hour": "productivity",
    "output per hour": "productivity",
    "getting more done per worker": "rising productivity",
    "the total amount of money out there": "the money supply",
    "how much money is in the economy": "the money supply",
    "how easy it is to turn into cash": "liquidity",
    "easy to turn into cash": "liquid",
    "hard to turn into cash": "illiquid",
    "hard to sell quickly": "illiquid",
    "how much one currency is worth in another": "the exchange rate",
    "what a dollar is worth abroad": "the exchange rate",
    "the dollar is strong": "the dollar has appreciated",
    "the dollar is weak": "the dollar has depreciated",
    "the dollar got stronger": "the dollar appreciated",
    "the dollar got weaker": "the dollar depreciated",
    "the currency lost value": "the currency depreciated",
    "the currency gained value": "the currency appreciated",
    "moving jobs overseas": "offshoring",
    "sending jobs abroad": "offshoring",
    "moving work to another country": "offshoring",
    "protecting local businesses from foreign competition": "protectionism",
    "keeping foreign goods out": "protectionism",
    "trading freely across borders": "free trade",
    "no barriers to trade": "free trade",
    "money migrants send home": "remittances",
    "money sent home from abroad": "remittances",
    "skilled people leaving the country": "brain drain",
    "the economy's ups and downs": "the business cycle",
    "boom and bust": "the business cycle",
    "slowing the economy without a crash": "a soft landing",
    "cooling the economy gently": "a soft landing",
    "slowing the economy so much it crashes": "a hard landing",
    "the economy is running too hot": "the economy is overheating",
    "growing too fast": "overheating",
    "stuck with no growth": "stagnation",
    "the economy is stuck": "the economy is stagnating",
    "not growing at all": "stagnant",
    "rising prices with no growth": "stagflation",
    "prices up but the economy stuck": "stagflation",
    "the economy is bouncing back": "the economy is recovering",
    "bouncing back": "recovering",
    "a sudden surprise that hits the economy": "an economic shock",
    "a surprise event that hits the economy": "an economic shock",
    "one step slowing everything down": "a bottleneck",
    "a choke point": "a bottleneck",
    "the chain of steps to get a product to you": "the supply chain",
    "how stuff gets from factory to store": "the supply chain",
    "things slowing the economy down": "headwinds",
    "things helping the economy": "tailwinds",
    "wants lower rates": "is dovish",
    "wants higher rates": "is hawkish",
    "prefers lower interest rates": "is dovish",
    "prefers higher interest rates": "is hawkish",
    "the bank that controls the money": "the central bank",
    "the country's main bank": "the central bank",
    "america's central bank": "the Federal Reserve",
    "the government's taxing and spending": "fiscal policy",
    "how the government taxes and spends": "fiscal policy",
    "what the central bank does with interest rates": "monetary policy",
    "how the central bank controls money": "monetary policy",
    "controlling interest rates": "monetary policy",
    "the central bank creating money to buy bonds": "quantitative easing",
    "the central bank buying up bonds": "quantitative easing",
    "the central bank pumping money in": "quantitative easing",
    "the central bank pulling money out": "quantitative tightening",
    "the central bank hinting at what it will do": "forward guidance",
    "what people think prices will do": "inflation expectations",
    "people expect prices to rise": "inflation expectations are rising",
    "aiming for two percent": "inflation targeting",
    "aiming for 2% inflation": "inflation targeting",
    "interest can't go below zero": "the zero lower bound",
    "cheap money isn't working": "a liquidity trap",
    "even free money isn't getting people to borrow": "a liquidity trap",
    "money already spent that you can't get back": "a sunk cost",
    "money already spent": "a sunk cost",
    "money you can't get back": "a sunk cost",
    "throwing good money after bad": "the sunk cost fallacy",
    "all else being equal": "ceteris paribus",
    "all other things being equal": "ceteris paribus",
    "everything else the same": "ceteris paribus",
    "holding everything else constant": "ceteris paribus",
    "one person's gain is another's loss": "zero-sum",
    "somebody has to lose for somebody to win": "zero-sum",
    "the whole economy": "the macroeconomy",
    "the big picture of the economy": "macroeconomics",
    "how individual people and businesses decide": "microeconomics",
    "a gentle push toward a better choice": "a nudge",
    "making the good choice the default": "a nudge",
    "how people actually make decisions": "behavioral economics",
    "the economy is connected to the whole world": "globalization",
    "the world getting more connected": "globalization",
    "poorer countries growing fast": "emerging markets",
    "fast-growing poorer countries": "emerging markets",
    "fast growing poorer countries": "emerging markets",
    "punishing a country by cutting off trade": "economic sanctions",
    "cutting off trade with a country": "sanctions",
    "foreign companies building factories here": "foreign direct investment",
    "money fleeing the country": "capital flight",
    "money rushing out of the country": "capital flight",
    "the number of jobs added": "nonfarm payrolls",
    "the jobs numbers": "the payrolls report",
    "the share of adults who work or want to": "the labor force participation rate",
    "people between jobs": "frictional unemployment",
    "between jobs": "frictionally unemployed",
    "jobs that disappeared because of new technology": "structural unemployment",
    "skills that don't match the jobs": "structural unemployment",
    "jobs lost because of a bad economy": "cyclical unemployment",
    "working less than you want": "underemployment",
    "working part time but wanting full time": "underemployment",
    "almost everyone has a job": "full employment",
    "everyone who wants a job has one": "full employment",
    "the lowest unemployment can go without prices rising": "the natural rate of unemployment",
    "the trade-off between jobs and prices": "the Phillips curve",
    "one dollar spent creates more than a dollar": "the multiplier effect",
    "spending that keeps getting re-spent": "the multiplier effect",
    "how fast money changes hands": "the velocity of money",
    "money moving quickly": "high money velocity",
    "government borrowing crowds out businesses": "crowding out",
    "the government borrowing so much that businesses can't": "crowding out",
    "the government takes over a company": "nationalization",
    "the government taking over": "nationalization",
    "selling a government business to private owners": "privatization",
    "selling off state companies": "privatization",
    "removing government rules": "deregulation",
    "cutting red tape": "deregulation",
    "getting rid of regulations": "deregulation",
    "rules for businesses": "regulation",
    "government rules": "regulation",
    "laws against companies getting too big": "antitrust law",
    "breaking up big companies": "antitrust enforcement",
    "stopping companies from getting too powerful": "antitrust",
    "obstacles that keep new competitors out": "barriers to entry",
    "hard for new companies to get in": "high barriers to entry",
    "easy for new companies to get in": "low barriers to entry",
    "being relatively better at one thing": "comparative advantage",
    "what you're comparatively best at": "your comparative advantage",
    "focus on what you're best at and trade": "comparative advantage",
    "an edge over rivals": "a competitive advantage",
    "an edge over competitors": "a competitive advantage",
    "value lost when the market is distorted": "deadweight loss",
    "value that just disappears": "deadweight loss",
    "the good deal you got": "consumer surplus",
    "paying less than you would have": "consumer surplus",
    "the extra a seller gets above their minimum": "producer surplus",
    "no one can be made better off without hurting someone": "Pareto efficiency",
    "new businesses wiping out old ones": "creative destruction",
    "innovation killing old industries": "creative destruction",
    "two companies joining together": "a merger",
    "two companies combining": "a merger",
    "one company buying another": "an acquisition",
    "buying another company": "an acquisition",
    "a company selling shares to the public for the first time": "an IPO",
    "going public": "an initial public offering",
    "money for risky young companies": "venture capital",
    "money invested in startups": "venture capital",
    "investors buying whole companies": "private equity",
    "a fund that just owns the whole market": "an index fund",
    "a fund that buys every stock": "an index fund",
    "spending on big long-term items": "capital expenditure",
    "spending on big equipment": "capital expenditure",
    "day-to-day running costs": "operating expenses",
    "day to day running costs": "operating expenses",
    "the money a business takes in": "revenue",
    "total money taken in": "revenue",
    "total sales": "revenue",
    "money left after costs": "profit",
    "money left over after paying everything": "net income",
    "what the company made": "earnings",
    "what a whole company is worth": "market capitalization",
    "what the company is worth on the stock market": "market capitalization",
    "the original amount borrowed": "the principal",
    "the amount you originally borrowed": "the principal",
    "interest earning interest": "compound interest",
    "interest on interest": "compound interest",
    "paying off a loan bit by bit": "amortization",
    "paying off a loan in installments": "amortization",
    "something you pledge to lose if you do not repay": "collateral",
    "what the bank takes if you don't pay": "collateral",
    "something the lender can take": "collateral",
    "what you own minus what you owe": "net worth",
    "money coming in versus money going out": "cash flow",
    "money coming in and going out": "cash flow",
    "something you own that has value": "an asset",
    "things you own": "assets",
    "something you owe": "a liability",
    "things you owe": "liabilities",
    "protection against a loss": "a hedge",
    "insurance against losing money": "a hedge",
    "a bet on something else's price": "a derivative",
    "bundles of home loans sold to investors": "mortgage-backed securities",
    "bundling loans to sell": "securitization",
    "a grade for how safe a borrower is": "a credit rating",
    "how likely someone is to pay you back": "creditworthiness",
    "extra return for extra risk": "a risk premium",
    "profit from selling something for more than you paid": "capital gains",
    "the profit when you sell": "capital gains",
    "profit from selling": "capital gains",
    "hundredths of a percent": "basis points",
    "digital money not run by any government": "cryptocurrency",
    "internet money": "cryptocurrency",
    "money backed by gold": "the gold standard",
    "money that's only valuable because the government says so": "fiat money",
    "money not backed by anything": "fiat money",
    "working gigs through apps": "the gig economy",
    "freelance work through apps": "the gig economy",
    "reusing and recycling instead of throwing away": "the circular economy",
    "buying and selling illegally": "the black market",
    "under the table": "in the informal economy",
    "off the books": "in the informal economy",
    "compared to last year": "year-over-year",
    "compared to the same time last year": "year-over-year",
    "compared to last quarter": "quarter-over-quarter",
    "compared to the previous three months": "quarter-over-quarter",
    "a three-month period": "a quarter",
    "smoothed for the time of year": "seasonally adjusted",
    "ignoring the holiday bump": "seasonally adjusted",
    "at a full-year pace": "annualized",
    "scaled up to a year": "annualized",
    "stretched out to a full year": "annualized",
    "one whole percent": "one percentage point",
    "a legal maximum price": "a price ceiling",
    "a legal minimum price": "a price floor",
    "prices that are slow to change": "sticky prices",
    "prices that don't change fast": "sticky prices",
    "the government controlling prices": "price controls",
    "the basics people need to live": "the cost of living",
    "what everyday life costs": "the cost of living",
    "how much it costs to live": "the cost of living",
    "how comfortably people live": "the standard of living",
    "a regular cash payment to everyone": "universal basic income",
    "free money for everyone": "universal basic income",
    "government money that lowers a price": "a subsidy",
    "the government paying part of the cost": "a subsidy",
    "government money to make it cheaper": "a subsidy",
    "the rich pay a higher rate": "a progressive tax",
    "a tax that hits the poor harder": "a regressive tax",
    "the tax on your next dollar": "the marginal tax rate",
    "a limit on how much can be imported": "an import quota",
    "a cap on imports": "an import quota",
    "a country making its money worth less": "devaluation",
    "making the currency worth less on purpose": "devaluation",
    "shielding local businesses": "protectionism",
    "rising prices": "inflation",
    "falling prices": "deflation",
    "runaway prices": "hyperinflation",
    "a shrinking economy": "a recession",
    "shrinking economy": "recession",
    "a deep long-lasting slump": "a depression",
    "prices rising more slowly": "disinflation",
    "sudden shortage of loans": "a credit crunch",
    "banks stopped lending": "a credit crunch",
    "paying down debt": "deleveraging",
    "paying off debts": "deleveraging",
    "can pay all their debts": "are solvent",
    "the government rescue of a company": "a bailout",
    "a rescue with public money": "a bailout",
    "the interest rate on long loans is lower than on short ones": "an inverted yield curve",
    "short-term loans paying more than long-term ones": "an inverted yield curve",
    "the return you earn on an investment": "the yield",
    "ownership in a company": "equity",
    "a company's payout to shareholders": "a dividend",
    "how wildly prices swing": "volatility",
    "a period of rising prices in the stock market": "a bull market",
    "a period of falling prices in the stock market": "a bear market",
    "a modest price drop after a run-up": "a correction",
    "a sudden steep price collapse": "a crash",
    "a quick rise in prices": "a rally",
    "the collection of investments someone owns": "a portfolio",
    "everything you've invested in": "your portfolio",
    "tradeable financial products": "securities",
    "stocks and bonds": "securities",
    "the everyday-prices gauge": "the consumer price index",
    "the measure of everyday prices": "the consumer price index",
    "how much prices went up this month": "the consumer price index",
    "total spending in the economy": "aggregate demand",
    "total production in the economy": "aggregate supply",
    "household spending": "consumption",
    "output per person": "GDP per capita",
    "what the economy could make at full stretch": "potential output",
    "the gap between what the economy makes and what it could make": "the output gap",
    "the basic ingredients for making things": "the factors of production",
    "the effect of one more": "the marginal effect",
    "government money given to people": "transfer payments",
    "government benefit programs": "entitlements",
    "built-in cushions in the budget": "automatic stabilizers",
    "the market getting it wrong on its own": "market failure",
    "many small sellers with identical products": "perfect competition",
    "self-interest accidentally helping everyone": "the invisible hand",
    "profiting by gaming the rules": "rent-seeking",
    "a basic raw good": "a commodity",
    "a person who buys things": "a consumer",
    "people who buy things": "consumers",
    "a business that makes things": "a producer",
    "businesses that make things": "producers",
    "someone who weighs costs and benefits": "a rational actor",
    "the wrong customers signing up": "adverse selection",
    "exports minus imports": "the balance of trade",
    "one person's gain is another person's loss": "zero-sum",
    "countries becoming more economically connected": "globalization",
    "an IOU that pays interest": "a bond",
    "the line of interest rates from short to long loans": "the yield curve",
    "the study of the whole economy": "macroeconomics",
    "the study of individual choices and markets": "microeconomics",
    "the study of strategic decisions": "game theory",
    "a situation where selfish choices leave everyone worse off": "a prisoner's dilemma",
    "anyone affected by a decision": "a stakeholder",
    "someone who owns part of a company": "a shareholder",
    "turn into money": "monetize",
    "make money from it": "monetize it",
    "the share of sales left after making the product": "the gross margin",
    "what families owe": "household debt",
    "the share of income people save": "the savings rate",
    "how optimistic people feel about money": "consumer confidence",
    "spending more because you feel richer": "the wealth effect",
    "the gap between what the rich and poor own": "wealth inequality",
    "the income level below which you count as poor": "the poverty line",
    "money that's worth less each year": "a depreciating asset",
}


# ------------------------------------------------------ extra forward
# Multi-word phrases that need a hand-written replacement (phrase -> (plain, term name)).
EXTRA_FORWARD = {
    "tariffs on imports": ("taxes on imports", "tariff"),
    "tariff on imports": ("tax on imports", "tariff"),
    "import tariffs": ("taxes on imports", "tariff"),
    "import tariff": ("tax on imports", "tariff"),
    "demand for": ("appetite for", "demand"),
    "supply of": ("amount available of", "supply"),
    "in demand": ("wanted", "demand"),
    "labor market": ("job market", "labor"),
    "labour market": ("job market", "labor"),
    "tight labor market": ("job market where workers are scarce", "labor"),
    "tight labour market": ("job market where workers are scarce", "labor"),
    "balance sheet": ("list of what it owns and owes", "asset"),
    "fed funds": ("the Fed's key interest rate", "federal funds rate"),
    "highly inelastic": ("barely price-sensitive", "inelastic"),
    "relatively inelastic": ("not very price-sensitive", "inelastic"),
    "highly elastic": ("very price-sensitive", "elastic"),
    "relatively elastic": ("fairly price-sensitive", "elastic"),
}


# ------------------------------------------------------------ protected
# Everyday phrases that contain a glossary word but must be left alone.
PROTECTED = [
    "credit card", "credit cards", "credit score", "real estate", "real world", "real life",
    "in return", "return to", "returned", "security guard", "social security", "by default",
    "default setting", "capital city", "capital letter", "capital hill", "capitol hill",
    "labor day", "labour day", "labor union", "labour union",
    "job market", "on demand", "demanding", "supply closet", "water supply",
    "power supply", "utility bill", "utility company", "utilities", "shock absorber",
    "shocked", "shocking", "a quarter past", "quarter past", "quarter to", "quarter mile",
    "correction officer", "boom box", "rally car", "pep rally", "hedge fund manager",
    "bond with", "james bond", "bonding", "principal of the school", "school principal",
    "asset to the team", "an asset to", "liability insurance", "consumer reports",
    "welfare check", "welfare office", "on welfare", "welfare benefits",
    "appreciate it", "i appreciate", "appreciate your", "depression and anxiety",
    "clinical depression", "mental depression", "recovery room", "in recovery",
    "recovering from", "expansion pack", "team expansion", "yield to", "yield sign",
    "equity in the workplace", "gender equity", "racial equity", "health equity",
    "rate limit", "heart rate", "exchange rate", "success rate", "crime rate", "birth rate",
    "growth mindset", "bottleneck effect", "bubble tea", "bubble wrap", "speech bubble",
    "market street", "farmers market", "farmer's market", "supermarket", "flea market",
    "stock up", "stock photo", "in stock", "out of stock", "livestock", "share with",
    "share a", "shared", "sharing", "cash flow statement", "profit and loss statement",
]
# Note: "exchange rate" is protected against the generic "interest rate"/"rates"
# patterns but is itself a glossary term, so it is re-added below.
PROTECTED = [p for p in PROTECTED if p != "exchange rate"]


# ------------------------------------------------------------------ result

@dataclass
class Found:
    matched: str        # text as it appeared in the input
    replacement: str    # what it became
    term: Term | None   # glossary entry, if any
    start: int          # span in the ORIGINAL input text
    end: int


@dataclass
class Result:
    original: str
    translated: str
    found: list = field(default_factory=list)   # list[Found], in order, unique by term
    grade_before: float | None = None
    hard_before: int = 0
    hard_after: int = 0

    @property
    def terms(self):
        """Unique glossary terms, in order of first appearance."""
        seen, out = set(), []
        for f in self.found:
            if f.term and f.term.term not in seen:
                seen.add(f.term.term)
                out.append(f.term)
        return out


# ------------------------------------------------------------------ engine

class Engine:
    def __init__(self):
        self.by_name = {t.term: t for t in TERMS}
        self._forward = self._build_forward()
        self._reverse = self._build_reverse()
        self._bps = re.compile(r"(\d+(?:\.\d+)?)\s*(?:basis\s+points?|bps?)(?![\w])", re.I)

    # -- building ---------------------------------------------------------
    def _build_forward(self):
        entries = []  # (phrase, replacement, term)
        for t in TERMS:
            for phrase in (t.term, *t.aliases):
                entries.append((phrase, _no_article(t.plain), t))
        for phrase, rep in SIMPLIFICATIONS.items():
            entries.append((phrase, rep, None))
        for phrase, (rep, name) in EXTRA_FORWARD.items():
            entries.append((phrase, rep, self.by_name[name]))
        for phrase in PROTECTED:
            entries.append((phrase, None, None))
        return self._compile(entries)

    def _build_reverse(self):
        entries = []
        for t in TERMS:
            entries.append((t.plain, t.term, t))
        for phrase, rep in REVERSE_PHRASES.items():
            # attach a glossary entry when the replacement contains a known term
            entries.append((phrase, rep, self._term_in(rep)))
        for phrase in PROTECTED:
            entries.append((phrase, None, None))
        return self._compile(entries)

    def _term_in(self, text):
        """Longest glossary term mentioned inside `text`, via the forward table."""
        regex, lookup = self._forward
        best = None
        for m in regex.finditer(text):
            term = lookup[m.lastgroup][2]
            if term and (best is None or len(m.group(0)) > best[0]):
                best = (len(m.group(0)), term)
        return best[1] if best else None

    @staticmethod
    def _compile(entries):
        # longest phrase first so the alternation prefers the most specific match
        entries = sorted({e[0].lower(): e for e in entries}.values(),
                         key=lambda e: (-len(e[0]), e[0]))
        lookup = {}
        alts = []
        for i, (phrase, rep, term) in enumerate(entries):
            name = f"e{i}"
            lookup[name] = (phrase, rep, term)
            alts.append(f"(?P<{name}>{_pattern_for(phrase)})")
        regex = re.compile("|".join(alts), re.I)
        return regex, lookup

    # -- translating ------------------------------------------------------
    def _apply(self, text, compiled, forward):
        regex, lookup = compiled
        found = []

        def sub(m):
            phrase, rep, term = lookup[m.lastgroup]
            if rep is None:            # protected phrase: leave untouched
                return m.group(0)
            if term and forward and term.keep:      # explain-only term
                found.append(Found(m.group(0), m.group(0), term, m.start(), m.end()))
                return m.group(0)
            if term and _is_plural_form(m.group(0), phrase, term.term):
                if forward:
                    rep = _no_article(term.plural) if term.plural else _pluralize(rep)
                elif rep.lower() == term.term:
                    rep = _pluralize(rep)
            before = text[:m.start()].rstrip()
            at_start = not before or before[-1] in ".!?:;\n\u2022-"
            out = _match_case(rep, m.group(0), at_start)
            found.append(Found(m.group(0), out, term, m.start(), m.end()))
            return out

        translated = regex.sub(sub, text)
        return translated, found

    def to_plain(self, text: str) -> Result:
        text = text.strip()
        if not text:
            return Result("", "")
        # "25 basis points" -> "0.25 percentage points" before anything else
        pre = self._bps.sub(lambda m: f"{float(m.group(1)) / 100:g} percentage points", text)
        translated, found = self._apply(pre, self._forward, True)
        if pre != text:
            # spans must refer to the original text, so re-scan it for highlighting
            _, found = self._apply(text, self._forward, True)
            bps = self.by_name["basis points"]
            for m in self._bps.finditer(text):
                found.insert(0, Found(m.group(0), "percentage points", bps, m.start(), m.end()))
        translated = self._tidy(translated)
        return Result(text, translated, found, reading_grade(text),
                      hard_words(text), hard_words(translated))

    def to_econ(self, text: str) -> Result:
        text = text.strip()
        if not text:
            return Result("", "")
        translated, found = self._apply(text, self._reverse, False)
        translated = self._tidy(translated)
        return Result(text, translated, found, reading_grade(text),
                      hard_words(text), hard_words(translated))

    @staticmethod
    def _tidy(s):
        s = re.sub(r"[ \t]{2,}", " ", s)
        s = re.sub(r"\s+([,.;:!?])", r"\1", s)
        # "the the", "a the", "an a" -> keep the first article
        s = re.sub(r"\b(the|a|an) (the|a|an) ", lambda m: m.group(1) + " ", s, flags=re.I)
        # "a interest rate" -> "an interest rate", "an shrinking" -> "a shrinking"
        s = re.sub(r"\b([Aa]) (?=[aeiouAEIOU])", lambda m: m.group(1) + "n ", s)
        s = re.sub(r"\b([Aa])n (?=[^aeiouAEIOU\W])", lambda m: m.group(1) + " ", s)
        return s.strip()

    def lookup(self, word: str) -> Term | None:
        """Exact lookup of a single term (any alias)."""
        w = word.strip().lower()
        for t in TERMS:
            if w == t.term or w in t.aliases or w == t.plain:
                return t
        return None


# ------------------------------------------------------------- formatting

def format_result(result: Result, direction: str) -> list:
    """
    Turn a Result into a list of (tag, text) chunks for a Tk text widget or
    plain printing. Tags: 'h' header, 'body', 'term', 'arrow', 'plain',
    'meaning', 'example', 'dim', 'nl'.
    """
    chunks = []
    if not result.original:
        return chunks

    if direction == "plain":
        chunks.append(("h", "PLAIN ENGLISH\n"))
    else:
        chunks.append(("h", "ECONOMICS\n"))
    chunks.append(("body", result.translated + "\n"))

    terms = result.terms
    if terms:
        chunks.append(("nl", "\n"))
        chunks.append(("h", "WHAT THE TERMS MEAN" if direction == "plain" else "TERMS USED"))
        chunks.append(("nl", "\n"))
        for t in terms:
            chunks.append(("term", t.term))
            chunks.append(("arrow", "  →  "))
            chunks.append(("plain", t.plain + "\n"))
            chunks.append(("meaning", t.meaning + "\n"))
            chunks.append(("example", "e.g. " + t.example + "\n"))
            chunks.append(("nl", "\n"))
    else:
        chunks.append(("nl", "\n"))
        if direction == "plain":
            chunks.append(("dim", "No economics jargon found. The text is already plain, or the term is not in the glossary yet.\n"))
        else:
            chunks.append(("dim", "No everyday phrases matched. Try describing the idea the way you would to a friend, e.g. 'prices keep going up'.\n"))

    stats = []
    if result.grade_before is not None:
        stats.append(f"original reading level: {grade_label(result.grade_before)}")
    if direction == "plain" and (result.hard_before or result.hard_after):
        stats.append(f"hard words: {result.hard_before} → {result.hard_after}")
    if stats:
        chunks.append(("dim", "  ·  ".join(stats) + "\n"))
    return chunks


def to_text(chunks) -> str:
    return "".join(text for _, text in chunks)


if __name__ == "__main__":
    import sys
    eng = Engine()
    direction = "plain"
    args = sys.argv[1:]
    if args and args[0] in ("--econ", "-e"):
        direction = "econ"
        args = args[1:]
    src = " ".join(args) or sys.stdin.read()
    r = eng.to_plain(src) if direction == "plain" else eng.to_econ(src)
    print(to_text(format_result(r, direction)))
