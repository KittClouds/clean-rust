#[derive(Clone, Copy)]
pub(crate) struct Month {
    pub(crate) name: &'static str,
    pub(crate) number: u8,
}

#[derive(Clone, Copy)]
pub(crate) struct Phrase {
    pub(crate) surface: &'static str,
    pub(crate) source_class: &'static str,
    pub(crate) normalized: &'static str,
    pub(crate) confidence_millis: u32,
    pub(crate) priority: u8,
}

pub(crate) const MONTHS: &[Month] = &[
    Month {
        name: "january",
        number: 1,
    },
    Month {
        name: "february",
        number: 2,
    },
    Month {
        name: "march",
        number: 3,
    },
    Month {
        name: "april",
        number: 4,
    },
    Month {
        name: "may",
        number: 5,
    },
    Month {
        name: "june",
        number: 6,
    },
    Month {
        name: "july",
        number: 7,
    },
    Month {
        name: "august",
        number: 8,
    },
    Month {
        name: "september",
        number: 9,
    },
    Month {
        name: "october",
        number: 10,
    },
    Month {
        name: "november",
        number: 11,
    },
    Month {
        name: "december",
        number: 12,
    },
];

pub(crate) const PHRASES: &[Phrase] = &[
    Phrase {
        surface: "today",
        source_class: "deictic_today",
        normalized: "REL:today",
        confidence_millis: 840,
        priority: 5,
    },
    Phrase {
        surface: "yesterday",
        source_class: "deictic_yesterday",
        normalized: "REL:yesterday",
        confidence_millis: 840,
        priority: 5,
    },
    Phrase {
        surface: "tomorrow",
        source_class: "deictic_tomorrow",
        normalized: "REL:tomorrow",
        confidence_millis: 840,
        priority: 5,
    },
    Phrase {
        surface: "tonight",
        source_class: "deictic_tonight",
        normalized: "REL:tonight",
        confidence_millis: 760,
        priority: 5,
    },
    Phrase {
        surface: "right before",
        source_class: "relative_boundary",
        normalized: "REL:before",
        confidence_millis: 680,
        priority: 4,
    },
    Phrase {
        surface: "previous save",
        source_class: "recurrence_marker",
        normalized: "RECURRENCE:previous_save",
        confidence_millis: 720,
        priority: 5,
    },
    Phrase {
        surface: "third time",
        source_class: "recurrence_marker",
        normalized: "RECURRENCE:third",
        confidence_millis: 740,
        priority: 5,
    },
    Phrase {
        surface: "fourth time",
        source_class: "recurrence_marker",
        normalized: "RECURRENCE:fourth",
        confidence_millis: 740,
        priority: 5,
    },
];
