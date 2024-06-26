import os
from datetime import datetime, timedelta
from typing import List, Literal

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from transformers import AutoTokenizer

from aristote.connectors.connectors import (
    APIConnectorWithOpenAIFormat,
    CustomOpenAIConnector,
)
from aristote.dtos import TranscribedText
from aristote.evaluation.evaluator import EvaluationPromptsConfig, Evaluator
from aristote.metadata_generation.main import metadata_generation
from aristote.metadata_generation.metadata_generator import (
    MetaData,
    MetadataPromptsConfig,
)
from aristote.quiz_generation.quiz_generator import (
    MultipleAnswerQuiz,
    QuizGenerator,
    QuizPromptsConfig,
)
from aristote.translation_generation.main import translation_generation
from aristote.translation_generation.translation_generator import (
    TranslationPromptsConfig,
)
from server.server_dtos import (
    AnswerPointer,
    Choice,
    EnrichmentVersionMetadata,
    EvaluationsWrapper,
    MultipleChoiceQuestion,
    QuizzesWrapper,
    Sentence,
    Transcript,
    TranscriptWrapper,
    TranslationInputtWrapper,
    TranslationOutputWrapper,
)

load_dotenv(".env")

language_map = {"fr": "french", "en": "english"}

MODEL_NAME = os.environ["MODEL_NAME"]
MODEL_PROMPTS_FOLDER = os.environ["MODEL_PROMPTS_FOLDER"]
VLLM_API_URL = os.environ["VLLM_API_URL"]
VLLM_TOKEN = os.environ["VLLM_TOKEN"]
VLLM_CACHE_PATH = os.environ["VLLM_CACHE_PATH"]

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_ORG_ID = os.environ.get("OPENAI_ORG_ID")
OPEN_AI_CACHE_PATH = os.environ.get("OPEN_AI_CACHE_PATH")
EVALUATION_MODEL_NAME = os.environ["EVALUATION_MODEL_NAME"]
EVALUATION_MODEL_PROMPTS_FOLDER = os.environ["EVALUATION_MODEL_PROMPTS_FOLDER"]

BATCH_SIZE = int(os.environ["BATCH_SIZE"])

app = FastAPI(
    title="Quiz Generation API",
    version="0.0.1",
    description="Generate quizzes from texts",
)
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
connector = APIConnectorWithOpenAIFormat(
    api_url=VLLM_API_URL,
    token=VLLM_TOKEN,
    cache_path=VLLM_CACHE_PATH,
)
openai_connector = CustomOpenAIConnector(
    api_key=OPENAI_API_KEY,
    organization=OPENAI_ORG_ID,
    cache_path=os.environ["OPEN_AI_CACHE_PATH"],
)


@app.get("/")
def root() -> dict:
    return {"message": "Welcome to the quiz generation API."}


@app.get("/health", tags=["health"])
def health() -> bool:
    return True


def format_time(seconds: int):
    duration = timedelta(seconds=seconds)
    base_date = datetime(1900, 1, 1)
    result_date = base_date + duration
    result_string = result_date.strftime("%H:%M:%S")
    return result_string


def get_promprt_path(env_path, language, evaluation: bool = False) -> str:
    return (
        os.environ[env_path]
        .replace("[language]", language_map[language])
        .replace(
            "[model_folder_name]",
            EVALUATION_MODEL_PROMPTS_FOLDER if evaluation else MODEL_PROMPTS_FOLDER,
        )
    )


def generate_quizzes(
    language: str,
    disciplines: List[str],
    media_types: List[str],
    transcripts: List[TranscribedText],
) -> QuizzesWrapper:
    if language in language_map.keys():
        metadata_prompt_config = MetadataPromptsConfig(
            reformulation_prompt_path=get_promprt_path(
                "REFORMULATION_PROMPT_PATH", language=language
            ),
            summary_prompt_path=get_promprt_path(
                "SUMMARY_PROMPT_PATH", language=language
            ),
            title_prompt_path=get_promprt_path("TITLE_PROMPT_PATH", language=language),
            description_prompt_path=get_promprt_path(
                "DESCRIPTION_PROMPT_PATH", language=language
            ),
            generate_topics_prompt_path=get_promprt_path(
                "GENERATE_TOPICS_PROMPT_PATH", language=language
            ),
            discipline_prompt_path=get_promprt_path(
                "DISCIPLINE_PROMPT_PATH", language=language
            ),
            media_type_prompt_path=get_promprt_path(
                "MEDIA_TYPE_PROMPT_PATH", language=language
            ),
            local_media_type_prompt_path=get_promprt_path(
                "LOCAL_MEDIA_TYPE_PROMPT_PATH", language=language
            ),
        )
        prompts_config = QuizPromptsConfig(
            quiz_generation_prompt=get_promprt_path(
                "QUIZ_GENERATION_PROMPT_PATH", language=language
            ),
            reformulation_prompt_path=get_promprt_path(
                "REFORMULATION_PROMPT_PATH", language=language
            ),
        )
    else:
        raise ValueError(f"Language {language} not supported.")

    metadata = metadata_generation(
        transcripts=transcripts,
        model_name=MODEL_NAME,
        tokenizer=tokenizer,
        connector=connector,
        prompts_config=metadata_prompt_config,
        disciplines=disciplines,
        media_types=media_types,
        batch_size=BATCH_SIZE,
    )
    quiz_generator = QuizGenerator(
        model_name=MODEL_NAME,
        tokenizer=tokenizer,
        api_connector=connector,
        prompts_config=prompts_config,
        chunks_path=None,
        batch_size=BATCH_SIZE,
    )
    quizzes = quiz_generator.full_generation(transcripts)
    formatted_quizzes = [
        MultipleChoiceQuestion(
            question=quiz.question,
            explanation=quiz.explanation,
            choices=[
                Choice(option_text=quiz.answer, correct_answer=True),
                Choice(option_text=quiz.fake_answer_1, correct_answer=False),
                Choice(option_text=quiz.fake_answer_2, correct_answer=False),
                Choice(option_text=quiz.fake_answer_3, correct_answer=False),
            ],
            answer_pointer=AnswerPointer(
                start_answer_pointer=format_time(quiz.origin_start),
                stop_answer_pointer=format_time(quiz.origin_end),
            ),
        )
        for quiz in quizzes
    ]
    return QuizzesWrapper(
        enrichment_version_metadata=EnrichmentVersionMetadata(
            title=metadata.title,
            description=metadata.description,
            topics=metadata.main_topics,
            discipline=metadata.discipline,
            media_type=metadata.media_type,
        ),
        multiple_choice_questions=formatted_quizzes,
    )


# TODO: Evaluate quizzes
def evaluate_quizzes(
    quizzes: QuizzesWrapper, language: Literal["fr", "en"] = "fr"
) -> EvaluationsWrapper:
    if language in language_map.keys():
        evaluation_prompts_config = EvaluationPromptsConfig(
            is_related_prompt=get_promprt_path(
                "IS_RELATED_PROMPT_PATH", language=language, evaluation=True
            ),
            is_self_contained_prompt=get_promprt_path(
                "IS_SELF_CONTAINED_PROMPT_PATH", language=language, evaluation=True
            ),
            is_question_prompt=get_promprt_path(
                "IS_QUESTION_PROMPT_PATH", language=language, evaluation=True
            ),
            language_is_clear_prompt=get_promprt_path(
                "LANGUAGE_IS_CLEAR_PROMPT_PATH", language=language, evaluation=True
            ),
            answers_are_all_different_prompt=get_promprt_path(
                "ANSWERS_ARE_ALL_DIFFERENT_PROMPT_PATH",
                language=language,
                evaluation=True,
            ),
            fake_answers_are_not_obvious_prompt=get_promprt_path(
                "FAKE_ANSWERS_ARE_NOT_OBVIOUS_PROMPT_PATH",
                language=language,
                evaluation=True,
            ),
            answers_are_related=get_promprt_path(
                "ANSWERS_ARE_RELATED_PROMPT_PATH", language=language, evaluation=True
            ),
            quiz_about_concept=get_promprt_path(
                "QUIZ_ABOUT_CONCEPT_PROMPT_PATH", language=language, evaluation=True
            ),
        )
    else:
        raise ValueError(f"Language {language} not supported.")
    title = quizzes.enrichment_version_metadata.title
    description = quizzes.enrichment_version_metadata.description
    evaluator = Evaluator(
        model_name=EVALUATION_MODEL_NAME,
        course_metadata=MetaData(
            title=title,
            description=description,
        ),
        tokenizer=tokenizer,
        connector=openai_connector,
        language=language,
        prompts_config=evaluation_prompts_config,
    )
    reformated_quizzes = [
        MultipleAnswerQuiz(
            id=quiz.id,
            question=quiz.question,
            answer=quiz.choices[0].option_text,
            fake_answer_1=quiz.choices[1].option_text,
            fake_answer_2=quiz.choices[2].option_text,
            fake_answer_3=quiz.choices[3].option_text,
            explanation=quiz.explanation,
        )
        for quiz in quizzes.multiple_choice_questions
    ]
    evaluations = evaluator.evaluate_quizzes(reformated_quizzes)
    return EvaluationsWrapper(evaluations=evaluations)


def translate_quizzes(
    enrichment: TranslationInputtWrapper, language: Literal["fr", "en"] = "en"
) -> TranslationOutputWrapper:
    if language in language_map.keys():
        translation_prompts_config = TranslationPromptsConfig(
            quiz_translation_prompt_path=get_promprt_path(
                "QUIZ_TRANSLATION_PROMPT_PATH", language=language
            ),
            title_translation_prompt_path=get_promprt_path(
                "TITLE_TRANSLATION_PROMPT_PATH", language=language
            ),
            description_translation_prompt_path=get_promprt_path(
                "DESCRIPTION_TRANSLATION_PROMPT_PATH", language=language
            ),
            topics_translation_prompt_path=get_promprt_path(
                "TOPICS_TRANSLATION_PROMPT_PATH", language=language
            ),
            transcript_translation_prompt_path=get_promprt_path(
                "TRANSCRIPT_TRANSLATION_PROMPT_PATH", language=language
            ),
        )
    else:
        raise ValueError(f"Language {language} not supported.")

    transcribed_sentences = [
        TranscribedText(
            text=sentence.text,
            start=sentence.start,
            end=sentence.end,
        )
        for sentence in enrichment.transcript.sentences
    ]

    translation = translation_generation(
        meta_data=MetaData(
            title=enrichment.enrichment_version_metadata.title,
            description=enrichment.enrichment_version_metadata.description,
            main_topics=enrichment.enrichment_version_metadata.topics,
        ),
        quizzes=[
            MultipleAnswerQuiz(
                id=multiple_choice_question.id,
                question=multiple_choice_question.question,
                explanation=multiple_choice_question.explanation,
                answer=multiple_choice_question.choices[0].option_text,
                fake_answer_1=multiple_choice_question.choices[1].option_text,
                fake_answer_2=multiple_choice_question.choices[2].option_text,
                fake_answer_3=multiple_choice_question.choices[3].option_text,
            )
            for multiple_choice_question in enrichment.multiple_choice_questions
        ],
        transcripts=transcribed_sentences,
        model_name=MODEL_NAME,
        prompts_config=translation_prompts_config,
        tokenizer=tokenizer,
        connector=connector,
        from_language=enrichment.from_language,
        to_language=enrichment.to_language,
        batch_size=BATCH_SIZE,
    )

    return TranslationOutputWrapper(
        enrichment_version_metadata=EnrichmentVersionMetadata(
            title=translation.meta_data.title,
            description=translation.meta_data.description,
            topics=translation.meta_data.main_topics,
        ),
        multiple_choice_questions=[
            MultipleChoiceQuestion(
                id=enrichment.multiple_choice_questions[quiz_index].id,
                question=quizz.question,
                explanation=quizz.explanation,
                choices=[
                    Choice(
                        id=enrichment.multiple_choice_questions[quiz_index]
                        .choices[0]
                        .id,
                        option_text=quizz.answer,
                        correct_answer=enrichment.multiple_choice_questions[quiz_index]
                        .choices[0]
                        .correct_answer,
                    ),
                    Choice(
                        id=enrichment.multiple_choice_questions[quiz_index]
                        .choices[1]
                        .id,
                        option_text=quizz.fake_answer_1,
                        correct_answer=enrichment.multiple_choice_questions[quiz_index]
                        .choices[1]
                        .correct_answer,
                    ),
                    Choice(
                        id=enrichment.multiple_choice_questions[quiz_index]
                        .choices[2]
                        .id,
                        option_text=quizz.fake_answer_2,
                        correct_answer=enrichment.multiple_choice_questions[quiz_index]
                        .choices[2]
                        .correct_answer,
                    ),
                    Choice(
                        id=enrichment.multiple_choice_questions[quiz_index]
                        .choices[3]
                        .id,
                        option_text=quizz.fake_answer_3,
                        correct_answer=enrichment.multiple_choice_questions[quiz_index]
                        .choices[3]
                        .correct_answer,
                    ),
                ],
            )
            for quiz_index, quizz in enumerate(translation.quizzes)
        ],
        transcript=Transcript(
            text=" ".join(
                [transcribed_text.text for transcribed_text in translation.transcript]
            ),
            sentences=[
                Sentence(
                    start=transcribed_text.start,
                    end=transcribed_text.end,
                    text=transcribed_text.text,
                )
                for transcribed_text in translation.transcript
            ],
        ),
        status="OK",
    )


@app.post("/generate-quizzes", response_model=QuizzesWrapper)
def generate(transcript: TranscriptWrapper) -> QuizzesWrapper:
    disciplines = transcript.disciplines
    media_types = transcript.media_types
    transcribed_sentences = [
        TranscribedText(
            text=sentence.text,
            start=sentence.start,
            end=sentence.end,
        )
        for sentence in transcript.transcript.sentences
    ]
    return generate_quizzes(
        transcript.transcript.language, disciplines, media_types, transcribed_sentences
    )


@app.post("/evaluate-quizzes", response_model=EvaluationsWrapper)
def evaluate(quizzes: QuizzesWrapper) -> EvaluationsWrapper:
    return evaluate_quizzes(quizzes)


@app.post("/translate-enrichment", response_model=TranslationOutputWrapper)
def translate(enrichment: TranslationInputtWrapper) -> TranslationOutputWrapper:
    return translate_quizzes(enrichment)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
