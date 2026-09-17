"""
seed_courses.py — write the subject descriptions.

INTO module text is summarised from the eight module specifications
(EAP, MDH, ADM, ECON, LIR, BAC, CSI, PHYS). Test-prep descriptions are
written from the awarding bodies' published formats.

    python seed_courses.py            fill in anything blank
    python seed_courses.py --overwrite  replace what is there
"""
import sys
from app import app
from models import Course, db

OVER = "--overwrite" in sys.argv
INTO = "INTO Qualifications"
L3   = "RQF Level 3"

C = {
"IQ-EAP": dict(
 name="English for Academic Purposes", mnemonic="01 IFY EAP",
 body=INTO, level=L3, credits=30, hours=300,
 desc="""The academic English module of the INTO International Foundation Programme. It builds the reading, writing, listening and speaking a student needs to study a degree taught in English, and the study habits that go with it.

Rather than general conversation, the focus is academic: reading long texts for argument, writing essays and reports with proper referencing, taking notes in lectures, and presenting and defending an idea. It runs alongside every pathway, so every foundation student takes it.""",
 assess="""Coursework portfolio — essays and reports written across the year
Listening and reading examination
Individual presentation with questions
Seminar participation, assessed continuously""",
 out="""Read academic texts critically and summarise the argument in your own words
Write structured essays and reports with a clear line of reasoning
Reference sources correctly and avoid plagiarism
Take useful notes from lectures and longer readings
Give an academic presentation and answer questions on it
Take part in seminars — agreeing, disagreeing and building on others
Use academic vocabulary and sentence structure accurately
Plan, draft and redraft written work to a deadline"""),

"IQ-MDH": dict(
 name="Mathematics and Data Handling", mnemonic="03 IFY MDH",
 body=INTO, level=L3, credits=30, hours=300,
 desc="""A broad mathematics module with a strong statistics strand, built for students heading into degrees that use data rather than pure mathematics — business, economics, social science and the life sciences.

It covers the core mathematics needed at foundation level: algebra, coordinate geometry, trigonometry and an introduction to calculus. Alongside that it treats data handling as a subject in its own right — how to collect data, present it honestly, analyse it, and say clearly what it does and does not show.

Assessment objectives follow those set for UK A-Level Mathematics, with statistics content added.""",
 assess="""Paper 1 — examination, 1 hour 50 minutes, 10 credits (covers the core mathematics)
Presentation — 5 to 10 minutes, 5 credits (covers the data handling section)
Paper 2 — examination, 2 hours 50 minutes, 15 credits (covers everything)""",
 out="""Part 1 — Number, algebra and coordinate geometry
Financial maths: percentages, percentage change, simple and compound interest
Algebra: expanding, factorising, indices, surds, algebraic and partial fractions
Coordinate geometry: gradients, equations of lines, intersections, lengths and areas
Quadratics: solving, f(x) notation, sketching, modelling, the discriminant
Polynomial division, the Factor Theorem and the Remainder Theorem
Simultaneous equations and inequalities, including graphically
Part 2 — Algebraic techniques
Exponentials and logarithms: graphs, growth and decay, the laws of logs
Binomial expansions and using them for approximations
Trigonometry: sine and cosine rules, area of a triangle, radians, arcs and sectors
Part 3 — Data handling
Sampling: choosing and evaluating a method in context
Measures of central tendency, location and spread; identifying outliers
Box plots, cumulative frequency curves and histograms
Correlation and regression: scatter diagrams, Pearson's and Spearman's, least squares
Probability: tree diagrams, Venn diagrams, mutually exclusive and independent events
Conditional probability
Probability distributions: discrete random variables, Binomial with hypothesis testing, Normal
Part 4 — Calculus
Differentiating polynomials; tangents, normals and stationary points
Rates of change in real contexts
Indefinite and definite integrals"""),

"IQ-ADM": dict(
 name="Mathematics (Advanced)", mnemonic="04 IFY ADM",
 body=INTO, level=L3, credits=30, hours=300,
 desc="""The specialist mathematics module, for students going on to engineering, physics, mathematics or computer science. It goes well beyond the Mathematics and Data Handling module and includes material drawn from UK Further Mathematics.

The emphasis is on calculus and vectors, with a solid grounding in pure mathematics and an introduction to mechanics and numerical methods. Students are expected to choose their own solution strategy on unfamiliar problems and to explain the reasoning behind it.

Delivery is five contact hours a week, split between lectures and practice sessions.""",
 assess="""Paper 1 — examination, 1 hour 30 minutes, 10 credits (covers algebra, geometry, trigonometry and introductory calculus)
Paper 2 — examination, 3 hours, 20 credits (covers the whole module)""",
 out="""Part 1 — Algebra and coordinate geometry
Indices including rational powers, expanding, factorising, surds, partial fractions
Linear simultaneous equations, gradients, equations of lines, intersections, inequalities
Quadratics: solving by three methods, sketching, the discriminant, quadratic inequalities
Polynomial division, the Remainder and Factor Theorems
Proof by exhaustion and disproof by counterexample
Part 2 — Trigonometry and calculus
Sine and cosine rules, area of a triangle, radians, arc length, sector and segment areas
Sketching cubic, quartic and reciprocal graphs; transformations; equation of a circle
Differentiation of polynomials; tangents, normals, stationary points, rates of change
Indefinite and definite integration; areas under and between curves
Part 3 — Algebraic techniques and further trigonometry
Binomial expansion for positive integer and rational powers, with validity ranges
Arithmetic and geometric progressions, recurrence relations, sigma notation
Exponentials and logarithms
Reciprocal trigonometric functions, identities, and solving trig equations
Addition and double-angle formulae; small-angle approximations
Part 4 — Further calculus, vectors and mechanics
The modulus function, mappings, domain and range, composite and inverse functions
Differentiating trig, exponential and log functions; chain, product and quotient rules
Implicit differentiation; integration by substitution and by parts
Vectors in two and three dimensions: magnitude, direction, position vectors
Mechanics: displacement-time and velocity-time graphs, constant acceleration, forces, Newton's first law
Numerical methods: change of sign, iteration, the Newton-Raphson procedure"""),

"IQ-ECON": dict(
 name="Economics", mnemonic="05 IFY ECON",
 body=INTO, level=L3, credits=30, hours=300,
 desc="""An introduction to economics as a way of thinking about how choices are made when resources are limited. The module covers both microeconomics — individual markets, firms and consumers — and macroeconomics, where the subject is a whole economy.

Students learn the standard models and, just as importantly, where those models break down. Real economies and current events are used throughout, so the theory is tested against what actually happens.

It is the core subject on the Business and Economics pathway and prepares students for degrees in economics, business, finance and management.""",
 assess="""Examination covering microeconomics
Examination covering macroeconomics
Data response and case study coursework
Individual or group presentation on an economic issue""",
 out="""Scarcity, choice and opportunity cost
Demand, supply and how prices are determined
Elasticity of demand and supply, and why it matters
How markets fail: externalities, public goods, information problems
Government intervention — and the cost of getting it wrong
Costs, revenue and profit; how firms behave
Market structures from perfect competition to monopoly
Measuring an economy: GDP, inflation, unemployment, the balance of payments
Aggregate demand and aggregate supply
Fiscal policy, monetary policy and supply-side policy
Economic growth, the trade cycle, and the trade-offs between objectives
International trade, exchange rates and globalisation
Interpreting economic data and reading it critically"""),

"IQ-LIR": dict(
 name="Law and International Relations", mnemonic="06 IFY LIR",
 body=INTO, level=L3, credits=30, hours=300,
 desc="""This module is built to help students think critically about the globalised world they live in, using English as the tool of analysis. It brings together three fields — law, politics and international relations — so that each informes the others.

Students study a range of legal and political systems from around the world and the tensions between them, then move on to international law, global governance, human rights, and how power is actually exercised between states.

Delivery is at least four hours a week of seminars, workshops and lectures, supported by structured independent study.""",
 assess="""Individual presentation on an aspect of law or international relations — 15 to 30 minutes, 10 credits
Examination covering all learning outcomes — 2 hours, 10 credits
Reflective learning log — continuous assessment across roughly 20 hours, 10 credits""",
 out="""Part 1 — Law
The definition and purposes of law in society; the roles of different courts
Case law and judicial precedent; how laws are made
Influences on parliamentary law making, and the strengths and weaknesses of each
Part 2 — Politics
The left-right continuum as a way of placing political ideas
Conservatism, liberalism and socialism, and how they differ from one another
The growth of nationalism, and globalism as a counter-current
Part 3 — International relations
Globalism: what drives it and how it shapes politics, economies and culture
Realism and liberalism as competing lenses on international relations
War, terrorism and the changing nature of conflict
The United Nations and global governance; responses to inequality and poverty
Part 4 — Human rights
The rules, principles and competing theories of human rights law
The Human Rights Act 1998; rights and liberties distinguished
Human rights in international law: the post-war settlement, the UDHR 1948, the ECHR 1953
Part 5 — Power and development
Hard power and the several versions of soft power
Great powers, emerging powers, and hegemony
The multipolar world today, and where it may be heading"""),

"IQ-BAC": dict(
 name="Business and Accounting", mnemonic="07 IFY BAC",
 body=INTO, level=L3, credits=30, hours=300,
 desc="""Two related subjects taught together: how businesses are organised and run, and how their performance is recorded and judged in numbers.

The business half covers objectives, ownership, structure, marketing, operations and people. The accounting half teaches students to construct and interpret the main financial statements and to use ratios to say something meaningful about a company's health.

Students work with real company reports, so the numbers are attached to actual decisions. It is a core subject on the Business pathway.""",
 assess="""Examination covering business organisation and strategy
Examination covering financial and management accounting
Business report or case study coursework
Presentation of a business analysis""",
 out="""Business objectives, ownership and legal structure
Stakeholders and where their interests conflict
Organisational structure, leadership and motivation
Marketing: the mix, segmentation, targeting and positioning
Operations: production methods, capacity, quality and the supply chain
The purpose of accounting and who uses the information
Double-entry bookkeeping and the trial balance
The income statement and the statement of financial position
Cash flow: forecasting it, and why profit is not cash
Ratio analysis — profitability, liquidity, efficiency and gearing
Interpreting a set of published accounts
Budgeting, variance analysis and break-even
Costing methods and what they are useful for
Investment appraisal and the basis of a sound business decision"""),

"IQ-CSI": dict(
 name="Computing Science", mnemonic="10 IFY CSI",
 body=INTO, level=L3, credits=30, hours=300,
 desc="""A foundation in computing that is equal parts theory and practice. Students learn to program, and they learn what is actually happening underneath — how data is represented, how a machine executes instructions, and why some problems are harder than others.

Alongside the technical content the module covers the consequences: data protection, security, and the ethical questions raised by the systems being built. Practical programming work runs throughout.

It prepares students for degrees in computer science, software engineering, data science and information systems.""",
 assess="""Written examination on computing theory
Programming project with documentation
Practical programming examination
Report on a legal, ethical or security issue in computing""",
 out="""Number systems: binary, hexadecimal, and converting between them
Representing text, images and sound as data
Boolean logic and logic gates
Computer architecture: the CPU, memory, the fetch-execute cycle
Hardware and software; the role of the operating system
Programming fundamentals: variables, types, selection, iteration
Subroutines, parameters and scope
Data structures: arrays, records, stacks, queues, linked lists
Algorithms for searching and sorting, and comparing their efficiency
Databases: tables, keys, relationships and SQL queries
Networks: topologies, protocols, the internet and how it fits together
Security: threats, encryption and defending a system
Data protection law and the ethics of computing
Software development: the lifecycle, testing and debugging"""),

"IQ-PHYS": dict(
 name="Physics", mnemonic="13 IFY PHYS",
 body=INTO, level=L3, credits=30, hours=300,
 desc="""Physics at foundation level, mapped to UK A-Level content, for students progressing to engineering, physics and the physical sciences.

The module works through mechanics, materials, electricity, waves and quantum phenomena, with fields and nuclear physics later on. Practical work is central — students learn to take measurements properly, handle uncertainty honestly, and write up an experiment so that someone else could repeat it.

It pairs with Mathematics (Advanced), which supplies the mathematical technique the physics depends on.""",
 assess="""Paper 1 — examination on mechanics, materials and electricity
Paper 2 — examination on waves, fields and nuclear physics
Practical assessment and laboratory portfolio
Data analysis task with uncertainty treatment""",
 out="""Measurement, SI units, significant figures and uncertainty
Scalars and vectors; resolving and combining them
Motion: displacement, velocity, acceleration, graphs and projectiles
Newton's laws, momentum and impulse
Work, energy, power and the conservation principles
Materials: density, Hooke's law, stress, strain and the Young modulus
Electricity: current, potential difference, resistance and resistivity
Circuits: series and parallel, EMF, internal resistance, potential dividers
Waves: properties, superposition, standing waves, diffraction and interference
Refraction, total internal reflection and optical fibres
Quantum phenomena: the photoelectric effect, photons, wave-particle duality
Circular motion and simple harmonic motion
Gravitational and electric fields
Capacitance, magnetic fields and electromagnetic induction
Nuclear physics: radioactivity, decay, fission and fusion
Practical skills: apparatus, technique, uncertainty and writing up"""),

"IQ-COMBINED": dict(
 name="IQ Combined (GED pending)", mnemonic=None, body=INTO, level=L3,
 credits=None, hours=None,
 desc="""A combined class for foundation students whose GED is still outstanding. Rather than starting a full pathway, students cover foundation study skills and the academic groundwork common to every route while they finish their GED subjects.

Once the GED is complete students move onto their chosen pathway — Business, Engineering, Computing Science or Law and International Relations — and pick up the specialist modules from there.""",
 assess="""Continuous assessment through class work
Progress reviews at each assessment point""",
 out="""Academic study skills: reading, note-taking, planning written work
Academic writing conventions and referencing
Numeracy and data handling groundwork
Preparation for the outstanding GED subjects
Introduction to the foundation pathway subjects"""),

"IELTS": dict(
 name="IELTS Preparation", mnemonic=None,
 body="British Council / IDP / Cambridge English", level="CEFR B1–C2",
 credits=None, hours=None,
 desc="""Preparation for the IELTS Academic test, which is what most universities and professional bodies ask for as proof of English. PIE is an IELTS test centre, so students prepare and sit the test in the same place.

The test has four parts — Listening, Reading, Writing and Speaking — and results are reported as band scores from 1 to 9. Each part gets its own band, and the overall score is the average of the four rounded to the nearest half band. Listening, Reading and Writing are taken on the same day, and take 2 hours 45 minutes in total.

Teaching covers technique as much as language. Knowing how the examiners mark each part is often what moves a band.""",
 assess="""Listening — 4 parts, 40 questions
Reading — 3 sections, 40 questions
Writing — Task 1 of about 150 words and Task 2 of about 250 words
Speaking — 3 parts, 11 to 14 minutes
Full mock tests under timed conditions, with feedback on writing and speaking""",
 out="""Listening for main ideas, detail, opinion and attitude across four recordings
Reading long academic texts quickly: skimming, scanning, locating detail
Handling every question type, including the ones designed to mislead
Writing Task 1: describing charts, graphs, processes and maps accurately
Writing Task 2: building and supporting an argument in a clear structure
Speaking Part 1: answering personal questions fluently
Speaking Part 2: the long turn, and using the preparation minute well
Speaking Part 3: discussing abstract ideas and justifying an opinion
Grammatical range and accuracy as the examiners assess it
Vocabulary for the common IELTS topics
Timing and exam technique under real conditions"""),

"GED-MATH": dict(
 name="GED Mathematical Reasoning", mnemonic=None,
 body="GED Testing Service", level="US high school equivalency",
 credits=None, hours=None,
 desc="""One of the four GED subjects. The test is 115 minutes in two parts, with a formula sheet and an on-screen calculator provided — so nothing needs memorising, but the methods need to be secure.

Questions are a mix of multiple choice, drag and drop, fill in the blank, select an area and drop down. Each GED subject is scored from 100 to 200 and 145 is a pass.

The emphasis is on applying mathematics to realistic problems rather than on abstract manipulation.""",
 assess="""Computer-based test, 115 minutes, two parts with a short break
Formula sheet and on-screen calculator provided
Pass mark 145 out of 200""",
 out="""Number sense: fractions, decimals, percentages, ratio and proportion
Signed numbers, exponents, roots and order of operations
Measurement, unit conversion and scale
Geometry: perimeter, area, surface area, volume, the Pythagorean theorem
Basic algebra: expressions, linear equations and inequalities
Quadratic equations and factorising
Coordinate geometry: plotting, gradient, the equation of a line
Functions, and reading them from tables and graphs
Interpreting graphs, charts and tables
Mean, median, mode, range and simple probability
Word problems, and translating them into mathematics"""),

"GED-RLA": dict(
 name="GED Reasoning Through Language Arts", mnemonic=None,
 body="GED Testing Service", level="US high school equivalency",
 credits=None, hours=None,
 desc="""The English subject of the GED, and the longest of the four at 150 minutes. It tests reading comprehension, command of standard written English, and the ability to write an argument — there is an extended response essay as well as 46 questions.

The essay asks students to read two short passages taking different positions, decide which is better argued, and explain why using evidence from the text. It is an argument-analysis task rather than a personal opinion piece.

Pass mark is 145 out of 200.""",
 assess="""Computer-based test, 150 minutes
46 questions plus one extended response essay
Pass mark 145 out of 200""",
 out="""Reading for meaning in fiction and non-fiction
Finding the main idea and the details that support it
Working out vocabulary from context
Identifying an author's purpose, tone and point of view
Analysing how an argument is built, and spotting weak reasoning
Comparing two texts that take different positions
Standard English grammar: agreement, tense, pronouns, modifiers
Sentence structure, punctuation and clarity
Planning and writing the extended response
Using evidence from a source text to support a claim
Editing your own writing for accuracy"""),

"GED-SCI": dict(
 name="GED Science", mnemonic=None,
 body="GED Testing Service", level="US high school equivalency",
 credits=None, hours=None,
 desc="""A 90-minute test of 34 questions covering life science, physical science, and earth and space science.

It is less about recalling facts than about reading science properly: interpreting data, following an experimental design, and judging whether a conclusion is actually supported by the evidence given. Much of the content is provided in the question itself.

Pass mark is 145 out of 200.""",
 assess="""Computer-based test, 90 minutes, 34 questions
Calculator available
Pass mark 145 out of 200""",
 out="""Life science: cells, heredity, evolution, body systems, ecosystems
Physical science: matter, chemical reactions, energy, motion and forces
Earth and space science: the Earth's systems, weather, the solar system, the universe
Reading scientific text and identifying the central idea
Interpreting graphs, tables and diagrams
Experimental design: variables, controls and sample size
Distinguishing a hypothesis, a theory and a conclusion
Judging whether evidence supports a claim
Using numbers in a scientific context: percentages, rates, scientific notation
Probability and statistics as they appear in science"""),

"GED-SS": dict(
 name="GED Social Studies", mnemonic=None,
 body="GED Testing Service", level="US high school equivalency",
 credits=None, hours=None,
 desc="""A 70-minute test of 35 questions across civics and government, history, economics and geography, with civics and government carrying the most weight.

As with Science, the skill being tested is reading and reasoning rather than recall. Questions are built on source material — a passage, a map, a political cartoon, a table of figures — and ask what it shows and how far it can be trusted.

Pass mark is 145 out of 200.""",
 assess="""Computer-based test, 70 minutes, 35 questions
Calculator available
Pass mark 145 out of 200""",
 out="""Civics and government: types of government, the US constitutional system, rights
How political power is structured, and how citizens participate
US history: the founding, the Civil War, industrialisation, the twentieth century
World history: revolutions, the world wars, the Cold War, decolonisation
Economics: markets, incentives, money and banking, government and the economy
Geography: population, migration, resources, and people's effect on the environment
Reading historical sources and identifying point of view and bias
Interpreting maps, charts, tables and political cartoons
Analysing historical arguments and the evidence behind them
Using numbers and graphics in a social studies context"""),

"SAT-MATH": dict(
 name="SAT Mathematics", mnemonic=None, body="College Board",
 level="US college admission", credits=None, hours=None,
 desc="""The Math half of the digital SAT: 44 questions in two 35-minute modules, 70 minutes in total, scored from 200 to 800.

The test is adaptive by module. Performance on the first module decides whether the second is harder or easier, and reaching the harder second module is what makes the top of the score range available. A calculator is allowed on every question and a reference sheet is built in.

Most questions are multiple choice; some require the student to type an answer.""",
 assess="""Two adaptive modules of 22 questions, 35 minutes each
Calculator permitted throughout; reference sheet built in
Scored 200 to 800, part of a 400 to 1600 total""",
 out="""Algebra: linear equations, inequalities, systems and their graphs
Advanced maths: quadratics, polynomials, exponentials, radicals, rational expressions
Functions: notation, transformations, and reading them from graphs
Problem solving and data analysis: ratio, rate, proportion, percentage
Interpreting statistics: mean, median, spread, scatter plots, lines of best fit
Probability and conditional probability from two-way tables
Geometry: lines, angles, triangles, circles, area and volume
Trigonometry: right triangles, the unit circle, radians
Pacing a module, and why banking time on easy questions matters
Using the built-in calculator and reference sheet efficiently
Typing student-produced responses in the correct form"""),

"SAT-ENG": dict(
 name="SAT Reading and Writing", mnemonic=None, body="College Board",
 level="US college admission", credits=None, hours=None,
 desc="""The Reading and Writing half of the digital SAT: 54 questions in two 32-minute modules, 64 minutes in total, scored from 200 to 800.

Each question comes with its own short passage, often a single paragraph — quite unlike the long reading blocks of the old paper test. That means resetting attention 54 times, which is its own skill.

Like the Math section it is adaptive by module, so the first module sets the score ceiling.""",
 assess="""Two adaptive modules of 27 questions, 32 minutes each
Scored 200 to 800, part of a 400 to 1600 total""",
 out="""Information and ideas: central ideas, detail, inference from a short text
Command of evidence: which detail supports a claim, textual and quantitative
Reading data in tables and graphs alongside a passage
Words in context: precise vocabulary choice
Text structure and purpose; the function of a particular sentence
Cross-text connections: comparing two short passages
Standard English conventions: sentence boundaries, agreement, punctuation
Verb tense, pronouns, modifiers and parallel structure
Expression of ideas: transitions and rhetorical synthesis
Working from notes to a sentence that meets a stated goal
Pacing across 54 short, unconnected questions"""),

"BASIC-ENG": dict(
 name="Basic English", mnemonic=None, body="PIE International Education",
 level="CEFR A1–B1", credits=None, hours=None,
 desc="""PIE's own foundation English course, for students who are not yet ready for IELTS or a foundation programme. It builds general English from the ground up — grammar, vocabulary, and the confidence to speak.

Classes are small and speaking-heavy, because the usual barrier is not knowledge but willingness to use it. Progress is measured against the CEFR levels, and most students move on to IELTS preparation once they reach a solid B1.""",
 assess="""Placement test at the start to set the right level
Regular unit tests on grammar and vocabulary
Speaking assessment each term
End-of-course test against CEFR level descriptors""",
 out="""Present, past and future tenses used accurately
Question forms, negatives and short answers
Articles, prepositions, countable and uncountable nouns
Comparatives, superlatives and modal verbs
Core vocabulary for everyday and study situations
Word building: prefixes, suffixes and common collocations
Listening to everyday speech at natural pace
Reading short texts for gist and for detail
Writing a paragraph, an email and a short description
Speaking about yourself, your routine and your opinions
Pronunciation: sounds, word stress and intonation
Taking part in a simple discussion without freezing"""),

"SPEAK": dict(
 name="Speaking Club", mnemonic=None, body="PIE International Education",
 level="All levels", credits=None, hours=None,
 desc="""A weekly session with one purpose: talking. No textbook, no exam, no marks.

Students discuss a topic in pairs and groups, present short ideas, and get feedback on fluency and pronunciation rather than on grammatical perfection. It runs alongside whatever else a student is studying and is particularly useful for anyone whose reading and writing have outpaced their speaking.

Attendance is the only requirement.""",
 assess="""No formal assessment
Informal feedback on fluency and pronunciation each session""",
 out="""Speaking for longer without hesitating
Expressing and defending an opinion
Agreeing, disagreeing and interrupting politely
Asking follow-up questions that keep a conversation going
Pronunciation and intonation in connected speech
Presenting a short idea to a group
Listening actively and responding to what was actually said
Losing the fear of making mistakes"""),
}


def main():
    with app.app_context():
        touched = skipped = missing = 0
        for code, d in C.items():
            c = Course.query.filter_by(course_code=code).first()
            if not c:
                print(f"   no such subject: {code}")
                missing += 1
                continue
            if c.description and not OVER:
                skipped += 1
                continue
            c.course_name    = d["name"]
            c.description    = d["desc"].strip()
            c.mnemonic       = d.get("mnemonic")
            c.awarding_body  = d.get("body")
            c.level          = d.get("level")
            c.credits        = d.get("credits")
            c.learning_hours = d.get("hours")
            c.assessment     = d["assess"].strip()
            c.outcomes       = d["out"].strip()
            touched += 1
            print(f"   {code:<14}{d['name'][:38]:<40}"
                  f"{len(d['out'].strip().splitlines())} topics")
        db.session.commit()
        print(f"\n   written {touched}, left alone {skipped}, not found {missing}")
        blank = [c.course_code for c in Course.query.all() if not c.description]
        print(f"   subjects still without a description: {blank or 'none'}")


if __name__ == "__main__":
    main()
