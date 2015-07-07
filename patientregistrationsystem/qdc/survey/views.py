# coding=utf-8
# from django.shortcuts import render

import re
import csv
import datetime

from StringIO import StringIO
from operator import itemgetter

from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, permission_required

from models import Survey
from forms import SurveyForm

from patient.models import Patient, QuestionnaireResponse as PatientQuestionnaireResponse

from experiment.models import ComponentConfiguration, Block, QuestionnaireResponse, Questionnaire, Group

from experiment.abc_search_engine import Questionnaires


@login_required
@permission_required('auth.view_survey')
def survey_list(request, template_name='survey/survey_list.html'):

    surveys = Questionnaires()

    questionnaires_list = []

    for survey in Survey.objects.all():
        questionnaires_list.append(
            {
                'id': survey.id,
                'lime_survey_id': survey.lime_survey_id,
                'title': surveys.get_survey_title(survey.lime_survey_id),
                'is_initial_evaluation': survey.is_initial_evaluation
            }
        )

    surveys.release_session_key()

    questionnaires_list = sorted(questionnaires_list, key=itemgetter('title'))

    data = {'questionnaires_list': questionnaires_list}
    return render(request, template_name, data)


def recursively_create_list_of_questionnaires(block_id, list_of_questionnaires_configuration):
    # Include questionnaires of this block to the list.
    questionnaire_configurations = ComponentConfiguration.objects.filter(parent_id=block_id,
                                                                         component__component_type="questionnaire")
    list_of_questionnaires_configuration += list(questionnaire_configurations)

    # Look for questionnaires in descendant blocks.
    block_configurations = ComponentConfiguration.objects.filter(parent_id=block_id,
                                                                 component__component_type="block")

    for block_configuration in block_configurations:
        list_of_questionnaires_configuration = recursively_create_list_of_questionnaires(
            Block.objects.get(id=block_configuration.component.id),
            list_of_questionnaires_configuration)

    return list_of_questionnaires_configuration


def create_experiments_questionnaire_data_dictionary(survey, surveys):
    # Create a list of questionnaires used in experiments by looking at questionnaires responses. We use a
    # dictionary because it is useful for filtering out duplicate component configurations from the list.
    experiments_questionnaire_data_dictionary = {}

    for qr in QuestionnaireResponse.objects.all():
        q = Questionnaire.objects.get(id=qr.component_configuration.component_id)

        if q.survey == survey:
            use = qr.component_configuration
            group = qr.subject_of_group.group

            if use.id not in experiments_questionnaire_data_dictionary:
                experiments_questionnaire_data_dictionary[use.id] = {
                    'experiment_title': group.experiment.title,
                    'group_title': group.title,
                    'parent_identification': use.parent.identification,
                    'component_identification': use.component.identification,
                    'use_name': use.name,
                    'patients': {}
                }

            patient = qr.subject_of_group.subject.patient

            if patient.id not in experiments_questionnaire_data_dictionary[use.id]['patients']:
                experiments_questionnaire_data_dictionary[use.id]['patients'][patient.id] = {
                    'patient_name': qr.subject_of_group.subject.patient.name,
                    'questionnaire_responses': []
                }

            response_result = surveys.get_participant_properties(q.survey.lime_survey_id,
                                                                 qr.token_id,
                                                                 "completed")

            experiments_questionnaire_data_dictionary[use.id]['patients'][patient.id]['questionnaire_responses'].append(
                {
                    'questionnaire_response': qr,
                    'completed': None if response_result is None else response_result != "N" and response_result != ""
                })

    surveys.release_session_key()

    # Add questionnaires from the experiments that have no answers, but are in an experimental protocol of a group.
    for g in Group.objects.all():
        if g.experimental_protocol is not None:
            list_of_component_configurations_for_questionnaires = \
                recursively_create_list_of_questionnaires(g.experimental_protocol.id, [])

            for use in list_of_component_configurations_for_questionnaires:
                q = Questionnaire.objects.get(id=use.component_id)

                if q.survey == survey:
                    if use.id not in experiments_questionnaire_data_dictionary:
                        experiments_questionnaire_data_dictionary[use.id] = {
                            'experiment_title': use.component.experiment.title,
                            'group_title': g.title,
                            'parent_identification': use.parent.identification,
                            'component_identification': use.component.identification,
                            'use_name': use.name,
                            'patients': {}  # There is no answers.
                        }

    # Add questionnaires from the experiments that have no answers and are not in an experimental protocol of a group.
    for use in ComponentConfiguration.objects.filter(component__component_type="questionnaire"):
        q = Questionnaire.objects.get(id=use.component_id)

        if q.survey == survey:
            if use.id not in experiments_questionnaire_data_dictionary:
                experiments_questionnaire_data_dictionary[use.id] = {
                    'experiment_title': use.component.experiment.title,
                    'group_title': '',  # It is not in use in any group.
                    'parent_identification': use.parent.identification,
                    'component_identification': use.component.identification,
                    'use_name': use.name,
                    'patients': {}  # There is no answers.
                }

    # Transform dictionary into a list to include questionnaire components that are not in use and to sort.
    experiments_questionnaire_data_list = []

    for key, value in experiments_questionnaire_data_dictionary.items():
        value['component_id'] = ComponentConfiguration.objects.get(id=key).component_id
        experiments_questionnaire_data_list.append(value)

    # Add questionnaires from the experiments that have no answers and are not even in use.
    for q in Questionnaire.objects.filter(survey=survey):
        already_included = False

        for dict in experiments_questionnaire_data_list:
            if q.id == dict['component_id']:
                already_included = True
                break

        if not already_included:
            experiments_questionnaire_data_list.append({
                'component_id': q.id,
                'experiment_title': q.experiment.title,
                'group_title': '',  # It is not in use in any group.
                'parent_identification': '',  # It is not in use in any set of steps.
                'component_identification': q.identification,
                'use_name': '',  # It is not in use in any set of steps.
                'patients': {}  # There is no answers.
            })

    # Sort by experiment title, group title, parent identification, step identification, and name of the use of step.
    # We considered the lower case version of the strings in the sorting
    # Empty strings appear after not-empty strings.
    # Reference: http://stackoverflow.com/questions/9386501/sorting-in-python-and-empty-strings
    experiments_questionnaire_data_list = sorted(experiments_questionnaire_data_list,
                                                 key=lambda x: (x['experiment_title'].lower(),
                                                                x['group_title'] == "",
                                                                x['group_title'].lower(),
                                                                x['parent_identification'] == "",
                                                                x['parent_identification'].lower(),
                                                                x['component_identification'].lower(),
                                                                x['use_name'] == "",
                                                                x['use_name'].lower()))

    return experiments_questionnaire_data_list


def create_patients_questionnaire_data_list(survey, surveys):
    # Create a list of patients by looking to the answers of this questionnaire. We do this way instead of looking for
    # patients and then looking for answers of each patient to reduce the number of access to the data base.
    # We use a dictionary because it is useful for filtering out duplicate patients from the list.
    patients_questionnaire_data_dictionary = {}
    for response in PatientQuestionnaireResponse.objects.filter(survey=survey):
        if response.patient.id not in patients_questionnaire_data_dictionary:
            patients_questionnaire_data_dictionary[response.patient.id] = {
                'patient_name': response.patient.name,
                'questionnaire_responses': []
            }

        response_result = surveys.get_participant_properties(response.survey.lime_survey_id,
                                                             response.token_id,
                                                             "completed")

        patients_questionnaire_data_dictionary[response.patient.id]['questionnaire_responses'].append({
            'questionnaire_response': response,
            'completed': None if response_result is None else response_result != "N" and response_result != ""
        })

    # Add to the dictionary patients that have not answered any questionnaire yet.
    if survey.is_initial_evaluation:
        patients = Patient.objects.filter(removed=False)

        for patient in patients:
            if patient.id not in patients_questionnaire_data_dictionary:
                patients_questionnaire_data_dictionary[patient.id] = {
                    'patient_name': patient.name,
                    'questionnaire_responses': []
                }

    # Transform the dictionary into a list, so that we can sort it by patient name.
    patients_questionnaire_data_list = []

    for key, dictionary in patients_questionnaire_data_dictionary.items():
        dictionary['patient_id'] = key
        patients_questionnaire_data_list.append(dictionary)

    patients_questionnaire_data_list = sorted(patients_questionnaire_data_list, key=itemgetter('patient_name'))

    return patients_questionnaire_data_list


@login_required
@permission_required('survey.view_survey')
def survey_view(request, survey_id, template_name="survey/survey_register.html"):
    survey = get_object_or_404(Survey, pk=survey_id)

    surveys = Questionnaires()
    limesurvey_available = check_limesurvey_access(request, surveys)
    survey_title = surveys.get_survey_title(survey.lime_survey_id)

    survey_form = SurveyForm(request.POST or None, instance=survey,
                             initial={'title': str(survey.lime_survey_id) + ' - ' + survey_title})

    for field in survey_form.fields:
        survey_form.fields[field].widget.attrs['disabled'] = True

    # if request.method == "POST":
    #     if request.POST['action'] == "remove":
    #         try:
    #             for keyword in research_project.keywords.all():
    #                 manage_keywords(keyword, ResearchProject.objects.exclude(id=research_project.id))
    #
    #             research_project.delete()
    #             return redirect('research_project_list')
    #         except ProtectedError:
    #             messages.error(request, "Erro ao tentar excluir o estudo.")

    patients_questionnaire_data_list = create_patients_questionnaire_data_list(survey, surveys)
    experiments_questionnaire_data_list = create_experiments_questionnaire_data_dictionary(survey, surveys)

    # TODO: control functionalities of remove, back, bread crumb etc.

    context = {
        "limesurvey_available": limesurvey_available,
        "patients_questionnaire_data_list": patients_questionnaire_data_list,
        "experiments_questionnaire_data_list": experiments_questionnaire_data_list,
        "survey": survey,
        "survey_form": survey_form,
        "survey_title": survey_title,
    }

    return render(request, template_name, context)


def get_questionnaire_responses(language_code, lime_survey_id, token_id):

    questionnaire_responses = []
    surveys = Questionnaires()
    token = surveys.get_participant_properties(lime_survey_id, token_id, "token")
    question_properties = []
    groups = surveys.list_groups(lime_survey_id)

    survey_title = surveys.get_survey_title(lime_survey_id)

    if not isinstance(groups, dict):

        # defining language to be showed
        languages = surveys.get_survey_languages(lime_survey_id)
        language = languages['language']
        if language_code in languages['additional_languages'].split(' '):
            language = language_code

        for group in groups:
            if 'id' in group and group['id']['language'] == language:

                question_list = surveys.list_questions(lime_survey_id, group['id'])
                question_list = sorted(question_list)

                for question in question_list:

                    properties = surveys.get_question_properties(question, group['id']['language'])

                    # cleaning the question field
                    properties['question'] = re.sub('{.*?}', '', re.sub('<.*?>', '', properties['question']))
                    properties['question'] = properties['question'].replace('&nbsp;', '').strip()

                    is_purely_formula = (properties['type'] == '*') and (properties['question'] == '')

                    if not is_purely_formula and properties['question'] != '':

                        if isinstance(properties['subquestions'], dict):
                            question_properties.append({
                                'question': properties['question'],
                                'question_id': properties['title'],
                                'answer_options': 'super_question',
                                'type': properties['type'],
                                'attributes_lang': properties['attributes_lang'],
                                'hidden': 'hidden' in properties['attributes'] and
                                          properties['attributes']['hidden'] == '1'
                            })
                            for key, value in sorted(properties['subquestions'].iteritems()):
                                question_properties.append({
                                    'question': value['question'],
                                    'question_id': properties['title'] + '[' + value['title'] + ']',
                                    'answer_options': properties['answeroptions'],
                                    'type': properties['type'],
                                    'attributes_lang': properties['attributes_lang'],
                                    'hidden': 'hidden' in properties['attributes'] and
                                              properties['attributes']['hidden'] == '1'
                                })
                        else:
                            question_properties.append({
                                'question': properties['question'],
                                'question_id': properties['title'],
                                'answer_options': properties['answeroptions'],
                                'type': properties['type'],
                                'attributes_lang': properties['attributes_lang'],
                                'hidden': 'hidden' in properties['attributes'] and
                                          properties['attributes']['hidden'] == '1'
                            })

        # Reading from Limesurvey and...
        responses_string = surveys.get_responses_by_token(lime_survey_id, token, language)

        # ... transforming to a list:
        # response_list[0] has the questions
        #   response_list[1] has the answers
        reader = csv.reader(StringIO(responses_string), delimiter=',')
        responses_list = []
        for row in reader:
            responses_list.append(row)

        for question in question_properties:

            if not question['hidden']:

                if isinstance(question['answer_options'], basestring) and \
                        question['answer_options'] == "super_question":

                    if question['question'] != '':
                        questionnaire_responses.append({
                            'question': question['question'],
                            'answer': '',
                            'type': question['type']
                        })
                else:

                    answer = ''

                    if question['type'] == '1':

                        answer_list = []

                        if question['question_id'] + "[1]" in responses_list[0]:
                            index = responses_list[0].index(question['question_id'] + "[1]")
                            answer_options = question['answer_options']
                            answer = question['attributes_lang']['dualscale_headerA'] + ": "
                            if responses_list[1][index] in answer_options:
                                answer_option = answer_options[responses_list[1][index]]
                                answer += answer_option['answer']
                            else:
                                answer += 'Sem resposta'

                        answer_list.append(answer)

                        if question['question_id'] + "[2]" in responses_list[0]:
                            index = responses_list[0].index(question['question_id'] + "[2]")
                            answer_options = question['answer_options']
                            answer = question['attributes_lang']['dualscale_headerB'] + ": "
                            if responses_list[1][index] in answer_options:
                                answer_option = answer_options[responses_list[1][index]]
                                answer += answer_option['answer']
                            else:
                                answer += 'Sem resposta'

                        answer_list.append(answer)

                        questionnaire_responses.append({
                            'question': question['question'],
                            'answer': answer_list,
                            'type': question['type']
                        })
                    else:

                        if question['question_id'] in responses_list[0]:

                            index = responses_list[0].index(question['question_id'])

                            answer_options = question['answer_options']

                            if isinstance(answer_options, dict):

                                if responses_list[1][index] in answer_options:
                                    answer_option = answer_options[responses_list[1][index]]
                                    answer = answer_option['answer']
                                else:
                                    answer = 'Sem resposta'
                            else:
                                if question['type'] == 'D':
                                    if responses_list[1][index]:
                                        answer = datetime.datetime.strptime(responses_list[1][index],
                                                                            '%Y-%m-%d %H:%M:%S')
                                    else:
                                        answer = ''
                                else:
                                    answer = responses_list[1][index]

                        questionnaire_responses.append({
                            'question': question['question'],
                            'answer': answer,
                            'type': question['type']
                        })

    surveys.release_session_key()

    return survey_title, questionnaire_responses


def check_limesurvey_access(request, surveys):
    limesurvey_available = True
    if not surveys.session_key:
        limesurvey_available = False
        messages.warning(request, "LimeSurvey indisponível. Sistema funcionando parcialmente.")

    return limesurvey_available