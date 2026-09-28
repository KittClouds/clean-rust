use super::*;

fn private_task() -> Task {
    Task {
        id: "t".into(),
        family_id: "f".into(),
        seed: 1,
        n: 3,
        k: 3,
        clauses: vec![
            Clause::Different { a: 0, b: 1 },
            Clause::Different { a: 1, b: 2 },
        ],
        role_anonymous: true,
    }
}

fn public_task() -> InferenceTask {
    InferenceTask {
        id: "t".into(),
        family_id: "f".into(),
        n: 3,
        k: 3,
        role_anonymous: true,
        global_text: String::new(),
        clauses: vec![
            "Do not assign e1 and e2 to the same role".into(),
            "e0 and e1 must have different roles".into(),
        ],
        entity_mentions: vec![vec![1, 2], vec![0, 1]],
        role_mentions: vec![vec![], vec![]],
    }
}

#[test]
fn public_private_edges_align_independently_of_render_order() {
    let edges = public_private_edges_match(&private_task(), &public_task()).unwrap();
    assert_eq!(edges, vec![(1, 2), (0, 1)]);
}

#[test]
fn edge_mismatch_fails_closed() {
    let mut public = public_task();
    public.entity_mentions[0] = vec![0, 2];
    assert!(public_private_edges_match(&private_task(), &public).is_err());
}

#[test]
fn unsupported_surface_or_non_different_ast_fails_closed() {
    let mut public = public_task();
    public.clauses[0] = "e1 and e2 share a role".into();
    assert!(public_private_edges_match(&private_task(), &public).is_err());
    let mut private = private_task();
    private.clauses[0] = Clause::Same { a: 0, b: 1 };
    assert!(public_private_edges_match(&private, &public_task()).is_err());
}
