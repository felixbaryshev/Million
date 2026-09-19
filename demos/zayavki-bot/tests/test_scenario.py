import pytest

from bot.scenario import Engine, Scenario, ScenarioError, Session

BASIC = {
    "steps": [
        {"id": "name", "question": "Как вас зовут?", "label": "Имя"},
        {"id": "phone", "question": "Телефон?", "type": "phone", "label": "Телефон"},
        {"id": "how", "question": "Как удобнее?", "type": "choice",
         "options": ["Доставка", "Самовывоз"], "label": "Способ"},
        {"id": "note", "question": "Комментарий?", "required": False,
         "label": "Комментарий"},
    ]
}


def run(answers, data=BASIC):
    engine = Engine(Scenario.from_dict(data))
    session = Session()
    engine.start(session)
    reply = None
    for answer in answers:
        reply = engine.answer(session, answer)
    return engine, session, reply


# --- загрузка конфига: падать рано и понятно -------------------------

def test_a_scenario_without_steps_is_rejected():
    with pytest.raises(ScenarioError, match="ни одного шага"):
        Scenario.from_dict({"greeting": "привет"})


def test_a_step_without_an_id_is_rejected():
    with pytest.raises(ScenarioError, match="не указан id"):
        Scenario.from_dict({"steps": [{"question": "Что?"}]})


def test_a_step_without_a_question_is_rejected():
    with pytest.raises(ScenarioError, match="не указан question"):
        Scenario.from_dict({"steps": [{"id": "x"}]})


def test_duplicate_ids_are_rejected():
    with pytest.raises(ScenarioError, match="уже использован"):
        Scenario.from_dict({"steps": [
            {"id": "a", "question": "1"}, {"id": "a", "question": "2"},
        ]})


def test_an_unknown_step_type_names_the_valid_ones():
    with pytest.raises(ScenarioError, match="phone"):
        Scenario.from_dict({"steps": [{"id": "a", "question": "?", "type": "date"}]})


def test_a_choice_without_options_is_rejected():
    with pytest.raises(ScenarioError, match="требует options"):
        Scenario.from_dict({"steps": [{"id": "a", "question": "?", "type": "choice"}]})


def test_options_on_a_text_step_are_rejected():
    with pytest.raises(ScenarioError, match="только для типа choice"):
        Scenario.from_dict({"steps": [
            {"id": "a", "question": "?", "options": ["x"]},
        ]})


def test_a_missing_file_is_reported_by_name():
    with pytest.raises(ScenarioError, match="не найден"):
        Scenario.from_yaml("/nonexistent/scenario.yaml")


def test_broken_yaml_is_reported_as_such(tmp_path):
    path = tmp_path / "s.yaml"
    path.write_text("steps: [\n  unclosed", encoding="utf-8")
    with pytest.raises(ScenarioError, match="YAML"):
        Scenario.from_yaml(str(path))


# --- прохождение диалога ---------------------------------------------

def test_a_full_pass_produces_a_lead():
    _, _, reply = run(["Иван", "8 916 123-45-67", "Доставка", "срочно"])
    assert reply.finished
    assert reply.lead == {
        "Имя": "Иван", "Телефон": "+79161234567",
        "Способ": "Доставка", "Комментарий": "срочно",
    }


def test_the_lead_uses_labels_not_ids():
    _, _, reply = run(["Иван", "89161234567", "1", "-"])
    assert "Имя" in reply.lead and "name" not in reply.lead


def test_a_step_without_a_label_falls_back_to_its_id():
    data = {"steps": [{"id": "wish", "question": "Что нужно?"}]}
    _, _, reply = run(["новый сайт"], data)
    assert reply.lead == {"wish": "новый сайт"}


def test_greeting_and_first_question_are_sent_separately():
    engine = Engine(Scenario.from_dict(BASIC))
    replies = engine.start(Session())
    assert len(replies) == 2
    assert "Здравствуйте" in replies[0].text
    assert "зовут" in replies[1].text


def test_a_choice_step_offers_its_options_as_buttons():
    engine = Engine(Scenario.from_dict(BASIC))
    session = Session()
    engine.start(session)
    engine.answer(session, "Иван")
    reply = engine.answer(session, "89161234567")
    assert reply.options == ["Доставка", "Самовывоз"]


def test_progress_is_reported_on_every_question():
    engine = Engine(Scenario.from_dict(BASIC))
    session = Session()
    _, first = engine.start(session)
    assert first.progress == "Вопрос 1 из 4"


# --- ошибки ввода ----------------------------------------------------

def test_a_bad_phone_repeats_the_step_instead_of_advancing():
    engine = Engine(Scenario.from_dict(BASIC))
    session = Session()
    engine.start(session)
    engine.answer(session, "Иван")
    reply = engine.answer(session, "не скажу")
    assert not reply.finished
    assert "телефон" in reply.text.lower()
    assert session.index == 1


def test_a_custom_error_message_is_used_when_given():
    data = {"steps": [{"id": "p", "question": "Телефон?", "type": "phone",
                       "error": "Нужен номер, иначе не перезвоним."}]}
    _, _, reply = run(["абв"], data)
    assert reply.text == "Нужен номер, иначе не перезвоним."


def test_recovery_after_a_bad_answer_keeps_the_dialogue_going():
    _, _, reply = run(["Иван", "мусор", "89161234567", "1", "-"])
    assert reply.finished
    assert reply.lead["Телефон"] == "+79161234567"


def test_a_junk_text_answer_is_refused():
    data = {"steps": [{"id": "wish", "question": "Что нужно?"}]}
    _, _, reply = run(["?"], data)
    assert not reply.finished


# --- необязательные шаги и навигация ---------------------------------

def test_an_optional_step_announces_how_to_skip():
    engine = Engine(Scenario.from_dict(BASIC))
    session = Session()
    engine.start(session)
    for answer in ("Иван", "89161234567", "1"):
        reply = engine.answer(session, answer)
    assert "«-»" in reply.text


@pytest.mark.parametrize("skip", ["-", "нет", "пропустить", "/skip"])
def test_optional_steps_accept_several_ways_to_skip(skip):
    _, _, reply = run(["Иван", "89161234567", "1", skip])
    assert reply.finished
    assert "Комментарий" not in reply.lead


def test_a_required_step_does_not_accept_a_skip():
    engine = Engine(Scenario.from_dict(BASIC))
    session = Session()
    engine.start(session)
    reply = engine.answer(session, "-")
    assert not reply.finished
    assert session.index == 0


def test_back_returns_to_the_previous_question_and_clears_it():
    engine = Engine(Scenario.from_dict(BASIC))
    session = Session()
    engine.start(session)
    engine.answer(session, "Иван")
    reply = engine.answer(session, "назад")
    assert session.index == 0
    assert "name" not in session.answers
    assert "зовут" in reply.text


def test_back_on_the_first_question_is_not_an_escape_hatch():
    engine = Engine(Scenario.from_dict(BASIC))
    session = Session()
    engine.start(session)
    engine.answer(session, "/back")
    assert session.index == 0


# --- состояние после завершения --------------------------------------

def test_answering_after_completion_does_not_create_a_second_lead():
    engine, session, reply = run(["Иван", "89161234567", "1", "-"])
    assert reply.finished
    again = engine.answer(session, "ещё")
    assert not again.finished
    assert "/start" in again.text


def test_start_resets_a_finished_session():
    engine, session, _ = run(["Иван", "89161234567", "1", "-"])
    engine.start(session)
    assert session.index == 0 and session.answers == {} and not session.done


def test_two_users_do_not_share_state():
    engine = Engine(Scenario.from_dict(BASIC))
    a, b = Session(), Session()
    engine.start(a)
    engine.start(b)
    engine.answer(a, "Иван")
    assert b.index == 0 and b.answers == {}


def test_back_on_the_first_question_is_not_recorded_as_the_answer():
    engine = Engine(Scenario.from_dict(BASIC))
    session = Session()
    engine.start(session)
    engine.answer(session, "назад")
    assert session.answers == {}
    assert session.index == 0
