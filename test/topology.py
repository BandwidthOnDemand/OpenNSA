"""
Sample topology for tests.
"""

SIMPLE_TOPOLOGY = """
{
    "A" : {
        "address"   : "nsa://localhost:4321",
        "endpoints" : [
            { "name" : "A1",    "config" : "a1c"                                                },
            { "name" : "A2",    "config" : "a2c",   "dest-network" : "B",   "dest-ep" : "B2"    },
            { "name" : "A3",    "config" : "a3c",   "dest-network" : "C",   "dest-ep" : "C2"    },
            { "name" : "A4",    "config" : "a4c",   "dest-network" : "D",   "dest-ep" : "D2"    }
        ]
    },

    "B" : {
        "address"   : "nsa://localhost:4322",
        "endpoints" : [
            { "name" : "B1",    "config" : "b1c"                                                },
            { "name" : "B2",    "config" : "b2c",   "dest-network" : "A",   "dest-ep" : "A2"    },
            { "name" : "B3",    "config" : "b3c",   "dest-network" : "E",   "dest-ep" : "E2"    }
        ]
    },

    "C" : {
        "address"   : "nsa://localhost:4323",
        "endpoints" : [
            { "name" : "C1",    "config" : "c1a"                                                },
            { "name" : "C2",    "config" : "c2c",   "dest-network" : "A",   "dest-ep" : "A2"    },
            { "name" : "C3",    "config" : "c3c",   "dest-network" : "E",   "dest-ep" : "E3"    },
            { "name" : "C4",    "config" : "c4c",   "dest-network" : "D",   "dest-ep" : "D3"    }
        ]
    },

    "D" : {
        "address"   : "nsa://localhost:4324",
        "endpoints" : [
            { "name" : "D1",    "config" : "d1c"                                                },
            { "name" : "D2",    "config" : "d2c",   "dest-network" : "A",   "dest-ep" : "A4"    },
            { "name" : "D3",    "config" : "d3c",   "dest-network" : "C",   "dest-ep" : "C4"    }
        ]
    },

    "E" : {
        "address"   : "nsa://localhost:4325",
        "endpoints" : [
            { "name" : "E1",    "config" : "e1c"                                                },
            { "name" : "E2",    "config" : "e2c",   "dest-network" : "B",   "dest-ep" : "B3"    },
            { "name" : "E3",    "config" : "e3c",   "dest-network" : "C",   "dest-ep" : "C3"    }
        ]
    }
}
"""

