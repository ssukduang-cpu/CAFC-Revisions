"""
Comprehensive Federal Circuit Landmark Cases (200+)

This module contains curated landmark cases organized by doctrine,
plus citation-discovery functions to find additional influential cases.
"""

# ============================================================================
# CURATED LANDMARK CASES (~65 essential cases)
# Organized by patent doctrine for systematic coverage
# ============================================================================

LANDMARK_CASES_BY_DOCTRINE = {
    # -------------------------------------------------------------------------
    # § 101 PATENT ELIGIBILITY (~15 cases)
    # -------------------------------------------------------------------------
    "eligibility": [
        {
            "name": "Alice Corp. v. CLS Bank International",
            "citation": "573 U.S. 208",
            "year": 2014,
            "significance": "Two-step abstract idea test",
            "search_terms": ["Alice", "CLS Bank"],
            "required_words": ["alice", "cls"]
        },
        {
            "name": "In re Bilski",
            "citation": "545 F.3d 943",
            "year": 2008,
            "significance": "Machine-or-transformation test",
            "search_terms": ["Bilski"],
            "required_words": ["bilski"]
        },
        {
            "name": "Enfish, LLC v. Microsoft Corp.",
            "citation": "822 F.3d 1327",
            "year": 2016,
            "significance": "Software as improvement to computer functionality",
            "search_terms": ["Enfish", "Microsoft"],
            "required_words": ["enfish"]
        },
        {
            "name": "McRO, Inc. v. Bandai Namco Games America Inc.",
            "citation": "837 F.3d 1299",
            "year": 2016,
            "significance": "Rules-based automation patent eligible",
            "search_terms": ["McRO", "Bandai"],
            "required_words": ["mcro"]
        },
        {
            "name": "Electric Power Group, LLC v. Alstom S.A.",
            "citation": "830 F.3d 1350",
            "year": 2016,
            "significance": "Data collection/analysis abstract",
            "search_terms": ["Electric Power Group", "Alstom"],
            "required_words": ["electric", "power", "group"]
        },
        {
            "name": "Berkheimer v. HP Inc.",
            "citation": "881 F.3d 1360",
            "year": 2018,
            "significance": "Step 2 factual inquiry",
            "search_terms": ["Berkheimer", "HP"],
            "required_words": ["berkheimer"]
        },
        {
            "name": "Athena Diagnostics, Inc. v. Mayo Collaborative Services, LLC",
            "citation": "927 F.3d 1333",
            "year": 2019,
            "significance": "Diagnostic method claims",
            "search_terms": ["Athena", "Mayo"],
            "required_words": ["athena", "diagnostics"]
        },
        {
            "name": "American Axle & Manufacturing, Inc. v. Neapco Holdings LLC",
            "citation": "967 F.3d 1285",
            "year": 2020,
            "significance": "Natural law in mechanical claims",
            "search_terms": ["American Axle", "Neapco"],
            "required_words": ["american", "axle"]
        },
        {
            "name": "Aatrix Software, Inc. v. Green Shades Software, Inc.",
            "citation": "882 F.3d 1121",
            "year": 2018,
            "significance": "Fact issues preclude 12(b)(6) dismissal",
            "search_terms": ["Aatrix", "Green Shades"],
            "required_words": ["aatrix"]
        },
        {
            "name": "Ariosa Diagnostics, Inc. v. Sequenom, Inc.",
            "citation": "788 F.3d 1371",
            "year": 2015,
            "significance": "Natural phenomenon in diagnostics",
            "search_terms": ["Ariosa", "Sequenom"],
            "required_words": ["ariosa", "sequenom"]
        },
        {
            "name": "buySAFE, Inc. v. Google, Inc.",
            "citation": "765 F.3d 1350",
            "year": 2014,
            "significance": "Contractual relationships abstract",
            "search_terms": ["buySAFE", "Google"],
            "required_words": ["buysafe"]
        },
        {
            "name": "DDR Holdings, LLC v. Hotels.com, L.P.",
            "citation": "773 F.3d 1245",
            "year": 2014,
            "significance": "Internet-specific solution eligible",
            "search_terms": ["DDR Holdings", "Hotels.com"],
            "required_words": ["ddr", "holdings"]
        },
        {
            "name": "Finjan, Inc. v. Blue Coat Systems, Inc.",
            "citation": "879 F.3d 1299",
            "year": 2018,
            "significance": "Security software eligible",
            "search_terms": ["Finjan", "Blue Coat"],
            "required_words": ["finjan"]
        },
        {
            "name": "CardioNet, LLC v. InfoBionic, Inc.",
            "citation": "955 F.3d 1358",
            "year": 2020,
            "significance": "Medical device software eligible",
            "search_terms": ["CardioNet", "InfoBionic"],
            "required_words": ["cardionet"]
        },
    ],
    
    # -------------------------------------------------------------------------
    # § 103 OBVIOUSNESS (~12 cases)
    # -------------------------------------------------------------------------
    "obviousness": [
        {
            "name": "KSR International Co. v. Teleflex Inc.",
            "citation": "550 U.S. 398",
            "year": 2007,
            "significance": "Flexible obviousness, TSM not required",
            "search_terms": ["KSR", "Teleflex"],
            "required_words": ["ksr", "teleflex"]
        },
        {
            "name": "In re Wands",
            "citation": "858 F.2d 731",
            "year": 1988,
            "significance": "Enablement factors",
            "search_terms": ["Wands"],
            "required_words": ["wands"]
        },
        {
            "name": "In re Dillon",
            "citation": "919 F.2d 688",
            "year": 1990,
            "significance": "Structural obviousness, burden shifting",
            "search_terms": ["Dillon"],
            "required_words": ["dillon"]
        },
        {
            "name": "Pfizer, Inc. v. Apotex, Inc.",
            "citation": "480 F.3d 1348",
            "year": 2007,
            "significance": "Obvious to try doctrine",
            "search_terms": ["Pfizer", "Apotex"],
            "required_words": ["pfizer", "apotex"]
        },
        {
            "name": "Takeda Chemical Industries, Ltd. v. Alphapharm Pty., Ltd.",
            "citation": "492 F.3d 1350",
            "year": 2007,
            "significance": "Lead compound analysis",
            "search_terms": ["Takeda", "Alphapharm"],
            "required_words": ["takeda", "alphapharm"]
        },
        {
            "name": "In re Kubin",
            "citation": "561 F.3d 1351",
            "year": 2009,
            "significance": "Biotechnology obviousness post-KSR",
            "search_terms": ["Kubin"],
            "required_words": ["kubin"]
        },
        {
            "name": "Ortho-McNeil Pharmaceutical, Inc. v. Mylan Laboratories, Inc.",
            "citation": "520 F.3d 1358",
            "year": 2008,
            "significance": "Unexpected results secondary considerations",
            "search_terms": ["Ortho-McNeil", "Mylan"],
            "required_words": ["ortho", "mcneil"]
        },
        {
            "name": "Apple Inc. v. Samsung Electronics Co.",
            "citation": "839 F.3d 1034",
            "year": 2016,
            "significance": "Design patent obviousness",
            "search_terms": ["Apple", "Samsung"],
            "required_words": ["apple", "samsung"]
        },
        {
            "name": "In re Cyclobenzaprine Hydrochloride Extended-Release Capsule Patent Litigation",
            "citation": "676 F.3d 1063",
            "year": 2012,
            "significance": "Formulation obviousness",
            "search_terms": ["Cyclobenzaprine"],
            "required_words": ["cyclobenzaprine"]
        },
        {
            "name": "Transocean Offshore Deepwater Drilling, Inc. v. Maersk Drilling USA, Inc.",
            "citation": "699 F.3d 1340",
            "year": 2012,
            "significance": "Combination of known elements",
            "search_terms": ["Transocean", "Maersk"],
            "required_words": ["transocean", "maersk"]
        },
        {
            "name": "In re Omeprazole Patent Litigation",
            "citation": "536 F.3d 1361",
            "year": 2008,
            "significance": "Pharmaceutical formulation",
            "search_terms": ["Omeprazole"],
            "required_words": ["omeprazole"]
        },
        {
            "name": "Leo Pharmaceutical Products, Ltd. v. Rea",
            "citation": "726 F.3d 1346",
            "year": 2013,
            "significance": "Unexpected results overcome prima facie case",
            "search_terms": ["Leo Pharmaceutical"],
            "required_words": ["leo", "pharmaceutical"]
        },
    ],
    
    # -------------------------------------------------------------------------
    # CLAIM CONSTRUCTION (~12 cases)
    # -------------------------------------------------------------------------
    "claim_construction": [
        {
            "name": "Phillips v. AWH Corp.",
            "citation": "415 F.3d 1303",
            "year": 2005,
            "significance": "Intrinsic evidence hierarchy",
            "search_terms": ["Phillips", "AWH"],
            "required_words": ["phillips", "awh"]
        },
        {
            "name": "Markman v. Westview Instruments, Inc.",
            "citation": "52 F.3d 967",
            "year": 1995,
            "significance": "Claim construction is matter of law",
            "search_terms": ["Markman", "Westview"],
            "required_words": ["markman", "westview"]
        },
        {
            "name": "Vitronics Corp. v. Conceptronic, Inc.",
            "citation": "90 F.3d 1576",
            "year": 1996,
            "significance": "Prosecution history as intrinsic evidence",
            "search_terms": ["Vitronics", "Conceptronic"],
            "required_words": ["vitronics"]
        },
        {
            "name": "Texas Digital Systems, Inc. v. Telegenix, Inc.",
            "citation": "308 F.3d 1193",
            "year": 2002,
            "significance": "Dictionary definitions (later limited by Phillips)",
            "search_terms": ["Texas Digital", "Telegenix"],
            "required_words": ["texas", "digital"]
        },
        {
            "name": "O2 Micro International Ltd. v. Beyond Innovation Technology Co.",
            "citation": "521 F.3d 1351",
            "year": 2008,
            "significance": "Court must construe disputed terms",
            "search_terms": ["O2 Micro", "Beyond Innovation"],
            "required_words": ["o2", "micro"]
        },
        {
            "name": "Teva Pharmaceuticals USA, Inc. v. Sandoz, Inc.",
            "citation": "789 F.3d 1335",
            "year": 2015,
            "significance": "Clear error review for subsidiary facts",
            "search_terms": ["Teva", "Sandoz"],
            "required_words": ["teva", "sandoz"]
        },
        {
            "name": "Cybor Corp. v. FAS Technologies, Inc.",
            "citation": "138 F.3d 1448",
            "year": 1998,
            "significance": "De novo appellate review (later modified)",
            "search_terms": ["Cybor", "FAS Technologies"],
            "required_words": ["cybor", "fas"]
        },
        {
            "name": "Thorner v. Sony Computer Entertainment America LLC",
            "citation": "669 F.3d 1362",
            "year": 2012,
            "significance": "Ordinary meaning presumption",
            "search_terms": ["Thorner", "Sony"],
            "required_words": ["thorner", "sony"]
        },
        {
            "name": "Nautilus, Inc. v. Biosig Instruments, Inc.",
            "citation": "134 S. Ct. 2120",
            "year": 2014,
            "significance": "Reasonable certainty standard",
            "search_terms": ["Nautilus", "Biosig"],
            "required_words": ["nautilus", "biosig"]
        },
        {
            "name": "Microsoft Corp. v. i4i Ltd. Partnership",
            "citation": "564 U.S. 91",
            "year": 2011,
            "significance": "Clear and convincing invalidity standard",
            "search_terms": ["Microsoft", "i4i"],
            "required_words": ["microsoft", "i4i"]
        },
        {
            "name": "Williamson v. Citrix Online, LLC",
            "citation": "792 F.3d 1339",
            "year": 2015,
            "significance": "Means-plus-function presumption",
            "search_terms": ["Williamson", "Citrix"],
            "required_words": ["williamson", "citrix"]
        },
        {
            "name": "Accent Packaging, Inc. v. Leggett & Platt, Inc.",
            "citation": "707 F.3d 1318",
            "year": 2013,
            "significance": "Claim term definiteness",
            "search_terms": ["Accent Packaging", "Leggett"],
            "required_words": ["accent", "packaging"]
        },
    ],
    
    # -------------------------------------------------------------------------
    # § 112 WRITTEN DESCRIPTION & ENABLEMENT (~10 cases)
    # -------------------------------------------------------------------------
    "written_description": [
        {
            "name": "Ariad Pharmaceuticals, Inc. v. Eli Lilly & Co.",
            "citation": "598 F.3d 1336",
            "year": 2010,
            "significance": "Possession requirement separate from enablement",
            "search_terms": ["Ariad", "Eli Lilly"],
            "required_words": ["ariad", "lilly"]
        },
        {
            "name": "Gentry Gallery, Inc. v. Berkline Corp.",
            "citation": "134 F.3d 1473",
            "year": 1998,
            "significance": "Disclosed embodiments limit claims",
            "search_terms": ["Gentry Gallery", "Berkline"],
            "required_words": ["gentry", "gallery"]
        },
        {
            "name": "Regents of the University of California v. Eli Lilly & Co.",
            "citation": "119 F.3d 1559",
            "year": 1997,
            "significance": "Biotech written description requirements",
            "search_terms": ["Regents", "Eli Lilly"],
            "required_words": ["regents", "lilly"]
        },
        {
            "name": "Enzo Biochem, Inc. v. Gen-Probe Inc.",
            "citation": "323 F.3d 956",
            "year": 2002,
            "significance": "Deposit of biological materials",
            "search_terms": ["Enzo Biochem", "Gen-Probe"],
            "required_words": ["enzo", "gen-probe"]
        },
        {
            "name": "Capon v. Eshhar",
            "citation": "418 F.3d 1349",
            "year": 2005,
            "significance": "Generic claim scope vs. disclosure",
            "search_terms": ["Capon", "Eshhar"],
            "required_words": ["capon", "eshhar"]
        },
        {
            "name": "Lockwood v. American Airlines, Inc.",
            "citation": "107 F.3d 1565",
            "year": 1997,
            "significance": "Software enablement requirements",
            "search_terms": ["Lockwood", "American Airlines"],
            "required_words": ["lockwood", "american", "airlines"]
        },
        {
            "name": "Wyeth & Cordis Corp. v. Abbott Laboratories",
            "citation": "720 F.3d 1380",
            "year": 2013,
            "significance": "Genus/species written description",
            "search_terms": ["Wyeth", "Abbott"],
            "required_words": ["wyeth", "abbott"]
        },
        {
            "name": "Amgen Inc. v. Sanofi",
            "citation": "987 F.3d 1080",
            "year": 2021,
            "significance": "Antibody enablement requirements",
            "search_terms": ["Amgen", "Sanofi"],
            "required_words": ["amgen", "sanofi"]
        },
        {
            "name": "Idenix Pharmaceuticals LLC v. Gilead Sciences Inc.",
            "citation": "941 F.3d 1149",
            "year": 2019,
            "significance": "Pharmaceutical enablement",
            "search_terms": ["Idenix", "Gilead"],
            "required_words": ["idenix", "gilead"]
        },
        {
            "name": "Nuvo Pharmaceuticals (Ireland) Designated Activity Co. v. Dr. Reddy's Laboratories Inc.",
            "citation": "923 F.3d 1368",
            "year": 2019,
            "significance": "Written description for known compounds",
            "search_terms": ["Nuvo", "Dr. Reddy"],
            "required_words": ["nuvo", "reddy"]
        },
    ],
    
    # -------------------------------------------------------------------------
    # INFRINGEMENT & DOCTRINE OF EQUIVALENTS (~10 cases)
    # -------------------------------------------------------------------------
    "infringement": [
        {
            "name": "Warner-Jenkinson Co. v. Hilton Davis Chemical Co.",
            "citation": "520 U.S. 17",
            "year": 1997,
            "significance": "Element-by-element equivalents test",
            "search_terms": ["Warner-Jenkinson", "Hilton Davis"],
            "required_words": ["warner", "jenkinson"]
        },
        {
            "name": "Festo Corp. v. Shoketsu Kinzoku Kogyo Kabushiki Co.",
            "citation": "535 U.S. 722",
            "year": 2002,
            "significance": "Prosecution history estoppel",
            "search_terms": ["Festo", "Shoketsu"],
            "required_words": ["festo"]
        },
        {
            "name": "Akamai Technologies, Inc. v. Limelight Networks, Inc.",
            "citation": "797 F.3d 1020",
            "year": 2015,
            "significance": "Divided infringement",
            "search_terms": ["Akamai", "Limelight"],
            "required_words": ["akamai", "limelight"]
        },
        {
            "name": "Limelight Networks, Inc. v. Akamai Technologies, Inc.",
            "citation": "572 U.S. 915",
            "year": 2014,
            "significance": "Induced infringement requires direct infringement",
            "search_terms": ["Limelight", "Akamai"],
            "required_words": ["limelight", "akamai"]
        },
        {
            "name": "BMC Resources, Inc. v. Paymentech, L.P.",
            "citation": "498 F.3d 1373",
            "year": 2007,
            "significance": "Joint infringement control test",
            "search_terms": ["BMC Resources", "Paymentech"],
            "required_words": ["bmc", "paymentech"]
        },
        {
            "name": "Commil USA, LLC v. Cisco Systems, Inc.",
            "citation": "135 S. Ct. 1920",
            "year": 2015,
            "significance": "Good-faith belief defense to inducement",
            "search_terms": ["Commil", "Cisco"],
            "required_words": ["commil", "cisco"]
        },
        {
            "name": "Global-Tech Appliances, Inc. v. SEB S.A.",
            "citation": "563 U.S. 754",
            "year": 2011,
            "significance": "Willful blindness for inducement",
            "search_terms": ["Global-Tech", "SEB"],
            "required_words": ["global-tech", "seb"]
        },
        {
            "name": "Graver Tank & Mfg. Co. v. Linde Air Products Co.",
            "citation": "339 U.S. 605",
            "year": 1950,
            "significance": "Doctrine of equivalents foundation",
            "search_terms": ["Graver Tank", "Linde"],
            "required_words": ["graver", "tank"]
        },
        {
            "name": "SciMed Life Systems, Inc. v. Advanced Cardiovascular Systems, Inc.",
            "citation": "242 F.3d 1337",
            "year": 2001,
            "significance": "Claim vitiation limit on DOE",
            "search_terms": ["SciMed", "Advanced Cardiovascular"],
            "required_words": ["scimed"]
        },
        {
            "name": "WMS Gaming Inc. v. International Game Technology",
            "citation": "184 F.3d 1339",
            "year": 1999,
            "significance": "Means-plus-function equivalents",
            "search_terms": ["WMS Gaming", "International Game"],
            "required_words": ["wms", "gaming"]
        },
    ],
    
    # -------------------------------------------------------------------------
    # DAMAGES & REMEDIES (~10 cases)
    # -------------------------------------------------------------------------
    "damages": [
        {
            "name": "Rite-Hite Corp. v. Kelley Co.",
            "citation": "56 F.3d 1538",
            "year": 1995,
            "significance": "Lost profits entire market value",
            "search_terms": ["Rite-Hite", "Kelley"],
            "required_words": ["rite-hite", "kelley"]
        },
        {
            "name": "Lucent Technologies, Inc. v. Gateway, Inc.",
            "citation": "580 F.3d 1301",
            "year": 2009,
            "significance": "Reasonable royalty Georgia-Pacific",
            "search_terms": ["Lucent", "Gateway"],
            "required_words": ["lucent", "gateway"]
        },
        {
            "name": "Uniloc USA, Inc. v. Microsoft Corp.",
            "citation": "632 F.3d 1292",
            "year": 2011,
            "significance": "25% rule of thumb rejected",
            "search_terms": ["Uniloc", "Microsoft"],
            "required_words": ["uniloc"]
        },
        {
            "name": "LaserDynamics, Inc. v. Quanta Computer, Inc.",
            "citation": "694 F.3d 51",
            "year": 2012,
            "significance": "Smallest salable unit",
            "search_terms": ["LaserDynamics", "Quanta"],
            "required_words": ["laserdynamics", "quanta"]
        },
        {
            "name": "VirnetX, Inc. v. Cisco Systems, Inc.",
            "citation": "767 F.3d 1308",
            "year": 2014,
            "significance": "Apportionment requirements",
            "search_terms": ["VirnetX", "Cisco"],
            "required_words": ["virnetx", "cisco"]
        },
        {
            "name": "WesternGeco LLC v. ION Geophysical Corp.",
            "citation": "138 S. Ct. 2129",
            "year": 2018,
            "significance": "Foreign lost profits recoverable",
            "search_terms": ["WesternGeco", "ION"],
            "required_words": ["westerngeco", "ion"]
        },
        {
            "name": "Halo Electronics, Inc. v. Pulse Electronics, Inc.",
            "citation": "136 S. Ct. 1923",
            "year": 2016,
            "significance": "Enhanced damages discretion",
            "search_terms": ["Halo", "Pulse"],
            "required_words": ["halo", "pulse"]
        },
        {
            "name": "Samsung Electronics Co. v. Apple Inc.",
            "citation": "137 S. Ct. 429",
            "year": 2016,
            "significance": "Design patent article of manufacture",
            "search_terms": ["Samsung", "Apple"],
            "required_words": ["samsung", "apple"]
        },
        {
            "name": "Power Integrations, Inc. v. Fairchild Semiconductor International, Inc.",
            "citation": "711 F.3d 1348",
            "year": 2013,
            "significance": "Foreign sales lost profits limitation",
            "search_terms": ["Power Integrations", "Fairchild"],
            "required_words": ["power", "integrations", "fairchild"]
        },
        {
            "name": "ResQNet.com, Inc. v. Lansa, Inc.",
            "citation": "594 F.3d 860",
            "year": 2010,
            "significance": "Comparable license analysis",
            "search_terms": ["ResQNet", "Lansa"],
            "required_words": ["resqnet"]
        },
    ],
    
    # -------------------------------------------------------------------------
    # WILLFULNESS & ENHANCED DAMAGES (~6 cases)
    # -------------------------------------------------------------------------
    "willfulness": [
        {
            "name": "In re Seagate Technology, LLC",
            "citation": "497 F.3d 1360",
            "year": 2007,
            "significance": "Objective recklessness standard (superseded by Halo)",
            "search_terms": ["Seagate"],
            "required_words": ["seagate"]
        },
        {
            "name": "Bard Peripheral Vascular, Inc. v. W.L. Gore & Associates, Inc.",
            "citation": "682 F.3d 1003",
            "year": 2012,
            "significance": "Willfulness jury instruction",
            "search_terms": ["Bard", "Gore"],
            "required_words": ["bard", "gore"]
        },
        {
            "name": "Read Corp. v. Portec, Inc.",
            "citation": "970 F.2d 816",
            "year": 1992,
            "significance": "Enhancement factors",
            "search_terms": ["Read Corp", "Portec"],
            "required_words": ["read", "portec"]
        },
        {
            "name": "SRI International, Inc. v. Cisco Systems, Inc.",
            "citation": "930 F.3d 1295",
            "year": 2019,
            "significance": "Post-Halo willfulness analysis",
            "search_terms": ["SRI International", "Cisco"],
            "required_words": ["sri", "cisco"]
        },
        {
            "name": "Eko Brands, LLC v. Adrian Rivera Maynez Enterprises, Inc.",
            "citation": "946 F.3d 1367",
            "year": 2020,
            "significance": "Enhanced damages discretion",
            "search_terms": ["Eko Brands", "Adrian Rivera"],
            "required_words": ["eko", "brands"]
        },
    ],
    
    # -------------------------------------------------------------------------
    # INJUNCTIONS (~5 cases)
    # -------------------------------------------------------------------------
    "injunctions": [
        {
            "name": "eBay Inc. v. MercExchange, L.L.C.",
            "citation": "547 U.S. 388",
            "year": 2006,
            "significance": "Four-factor injunction test",
            "search_terms": ["eBay", "MercExchange"],
            "required_words": ["ebay", "mercexchange"]
        },
        {
            "name": "Robert Bosch LLC v. Pylon Manufacturing Corp.",
            "citation": "659 F.3d 1142",
            "year": 2011,
            "significance": "Irreparable harm post-eBay",
            "search_terms": ["Robert Bosch", "Pylon"],
            "required_words": ["bosch", "pylon"]
        },
        {
            "name": "Apple Inc. v. Samsung Electronics Co.",
            "citation": "809 F.3d 633",
            "year": 2015,
            "significance": "Causal nexus requirement",
            "search_terms": ["Apple", "Samsung", "injunction"],
            "required_words": ["apple", "samsung"]
        },
        {
            "name": "i4i Ltd. Partnership v. Microsoft Corp.",
            "citation": "598 F.3d 831",
            "year": 2010,
            "significance": "Injunction pending appeal",
            "search_terms": ["i4i", "Microsoft"],
            "required_words": ["i4i", "microsoft"]
        },
    ],
    
    # -------------------------------------------------------------------------
    # IPR/PTAB PROCEDURE (~8 cases)
    # -------------------------------------------------------------------------
    "ipr_ptab": [
        {
            "name": "Cuozzo Speed Technologies, LLC v. Lee",
            "citation": "136 S. Ct. 2131",
            "year": 2016,
            "significance": "BRI claim construction in IPR",
            "search_terms": ["Cuozzo", "Lee"],
            "required_words": ["cuozzo"]
        },
        {
            "name": "SAS Institute Inc. v. Iancu",
            "citation": "138 S. Ct. 1348",
            "year": 2018,
            "significance": "Must decide all challenged claims",
            "search_terms": ["SAS Institute", "Iancu"],
            "required_words": ["sas", "institute"]
        },
        {
            "name": "Oil States Energy Services, LLC v. Greene's Energy Group, LLC",
            "citation": "138 S. Ct. 1365",
            "year": 2018,
            "significance": "IPR constitutionality",
            "search_terms": ["Oil States", "Greene's Energy"],
            "required_words": ["oil", "states"]
        },
        {
            "name": "Aqua Products, Inc. v. Matal",
            "citation": "872 F.3d 1290",
            "year": 2017,
            "significance": "Burden of proof for amended claims",
            "search_terms": ["Aqua Products", "Matal"],
            "required_words": ["aqua", "products"]
        },
        {
            "name": "Thryv, Inc. v. Click-To-Call Technologies, LP",
            "citation": "140 S. Ct. 1367",
            "year": 2020,
            "significance": "Time-bar institution non-appealable",
            "search_terms": ["Thryv", "Click-To-Call"],
            "required_words": ["thryv"]
        },
        {
            "name": "In re Magnum Oil Tools International, Ltd.",
            "citation": "829 F.3d 1364",
            "year": 2016,
            "significance": "Claim amendment procedure",
            "search_terms": ["Magnum Oil"],
            "required_words": ["magnum", "oil"]
        },
        {
            "name": "Wi-Fi One, LLC v. Broadcom Corp.",
            "citation": "878 F.3d 1364",
            "year": 2018,
            "significance": "Time-bar estoppel appealable",
            "search_terms": ["Wi-Fi One", "Broadcom"],
            "required_words": ["wi-fi", "broadcom"]
        },
        {
            "name": "Arthrex, Inc. v. Smith & Nephew, Inc.",
            "citation": "941 F.3d 1320",
            "year": 2019,
            "significance": "APJ appointments clause (later Supreme Court)",
            "search_terms": ["Arthrex", "Smith Nephew"],
            "required_words": ["arthrex"]
        },
    ],
    
    # -------------------------------------------------------------------------
    # INEQUITABLE CONDUCT (~5 cases)
    # -------------------------------------------------------------------------
    "inequitable_conduct": [
        {
            "name": "Therasense, Inc. v. Becton, Dickinson & Co.",
            "citation": "649 F.3d 1276",
            "year": 2011,
            "significance": "But-for materiality, specific intent",
            "search_terms": ["Therasense", "Becton"],
            "required_words": ["therasense", "becton"]
        },
        {
            "name": "Kingsdown Medical Consultants, Ltd. v. Hollister Inc.",
            "citation": "863 F.2d 867",
            "year": 1988,
            "significance": "Gross negligence insufficient",
            "search_terms": ["Kingsdown", "Hollister"],
            "required_words": ["kingsdown", "hollister"]
        },
        {
            "name": "1st Media, LLC v. Electronic Arts, Inc.",
            "citation": "694 F.3d 1367",
            "year": 2012,
            "significance": "Post-Therasense application",
            "search_terms": ["1st Media", "Electronic Arts"],
            "required_words": ["1st", "media", "electronic"]
        },
        {
            "name": "American Calcar, Inc. v. American Honda Motor Co.",
            "citation": "768 F.3d 1185",
            "year": 2014,
            "significance": "Egregious misconduct exception",
            "search_terms": ["American Calcar", "Honda"],
            "required_words": ["calcar", "honda"]
        },
        {
            "name": "Network Signatures, Inc. v. State Farm Mutual Automobile Insurance Co.",
            "citation": "731 F.3d 1239",
            "year": 2013,
            "significance": "Intent inference from evidence",
            "search_terms": ["Network Signatures", "State Farm"],
            "required_words": ["network", "signatures"]
        },
    ],
    
    # -------------------------------------------------------------------------
    # DESIGN PATENTS (~4 cases)
    # -------------------------------------------------------------------------
    "design_patents": [
        {
            "name": "Egyptian Goddess, Inc. v. Swisa, Inc.",
            "citation": "543 F.3d 665",
            "year": 2008,
            "significance": "Ordinary observer test",
            "search_terms": ["Egyptian Goddess", "Swisa"],
            "required_words": ["egyptian", "goddess"]
        },
        {
            "name": "Gorham Co. v. White",
            "citation": "81 U.S. 511",
            "year": 1871,
            "significance": "Design patent infringement standard",
            "search_terms": ["Gorham", "White"],
            "required_words": ["gorham"]
        },
        {
            "name": "Crocs, Inc. v. International Trade Commission",
            "citation": "598 F.3d 1294",
            "year": 2010,
            "significance": "Design patent claim scope",
            "search_terms": ["Crocs", "ITC"],
            "required_words": ["crocs"]
        },
        {
            "name": "Richardson v. Stanley Works, Inc.",
            "citation": "597 F.3d 1288",
            "year": 2010,
            "significance": "Functional features in design patents",
            "search_terms": ["Richardson", "Stanley Works"],
            "required_words": ["richardson", "stanley"]
        },
    ],
}

def get_all_curated_cases():
    """Return flat list of all curated landmark cases."""
    all_cases = []
    for doctrine, cases in LANDMARK_CASES_BY_DOCTRINE.items():
        for case in cases:
            case_copy = case.copy()
            case_copy["doctrine"] = doctrine
            all_cases.append(case_copy)
    return all_cases

def get_cases_by_doctrine(doctrine: str):
    """Return cases for a specific doctrine."""
    return LANDMARK_CASES_BY_DOCTRINE.get(doctrine, [])

def count_curated_cases():
    """Return total count of curated cases."""
    return sum(len(cases) for cases in LANDMARK_CASES_BY_DOCTRINE.values())
