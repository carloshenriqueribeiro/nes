# coding=utf-8
from functools import partial
import re
import datetime
import csv

from StringIO import StringIO

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.urlresolvers import reverse
from django.db.models import Q
from django.db.models.deletion import ProtectedError
# from django.forms import HiddenInput
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render, render_to_response

from experiment.models import Experiment, Subject, QuestionnaireResponse, SubjectOfGroup, Group, Component, \
    ComponentConfiguration, Questionnaire, Task, Stimulus, Pause, Instruction, Block, \
    TaskForTheExperimenter, ClassificationOfDiseases, ResearchProject, Keyword, PatientQuestionnaireResponse
from experiment.forms import ExperimentForm, QuestionnaireResponseForm, FileForm, GroupForm, InstructionForm, \
    ComponentForm, StimulusForm, BlockForm, ComponentConfigurationForm, ResearchProjectForm
from patient.models import Patient
from experiment.abc_search_engine import Questionnaires

from operator import itemgetter


permission_required = partial(permission_required, raise_exception=True)

icon_class = {
    u'block': 'glyphicon glyphicon-th-large',
    u'instruction': 'glyphicon glyphicon-comment',
    u'pause': 'glyphicon glyphicon-time',
    u'questionnaire': 'glyphicon glyphicon-list-alt',
    u'stimulus': 'glyphicon glyphicon-headphones',
    u'task': 'glyphicon glyphicon-check',
    u'task_experiment': 'glyphicon glyphicon-wrench'
}

delimiter = "-"

# pylint: disable=E1101
# pylint: disable=E1103


@login_required
@permission_required('experiment.view_researchproject')
def research_project_list(request, template_name="experiment/research_project_list.html"):
    research_projects = ResearchProject.objects.order_by('start_date')
    context = {"research_projects": research_projects}

    return render(request, template_name, context)


@login_required
@permission_required('experiment.add_researchproject')
def research_project_create(request, template_name="experiment/research_project_register.html"):
    research_project_form = ResearchProjectForm(request.POST or None)

    if request.method == "POST":

        if request.POST['action'] == "save":

            if research_project_form.is_valid():
                research_project_added = research_project_form.save()

                messages.success(request, 'Estudo criado com sucesso.')

                redirect_url = reverse("research_project_view", args=(research_project_added.id,))
                return HttpResponseRedirect(redirect_url)

    context = {
        "research_project_form": research_project_form,
        "creating": True,
        "editing": True}

    return render(request, template_name, context)


@login_required
@permission_required('experiment.change_researchproject')
def research_project_view(request, research_project_id, template_name="experiment/research_project_register.html"):
    research_project = get_object_or_404(ResearchProject, pk=research_project_id)
    research_project_form = ResearchProjectForm(request.POST or None, instance=research_project)

    for field in research_project_form.fields:
        research_project_form.fields[field].widget.attrs['disabled'] = True

    if request.method == "POST":
        if request.POST['action'] == "remove":
            try:
                for keyword in research_project.keywords.all():
                    manage_keywords(keyword, ResearchProject.objects.exclude(id=research_project.id))

                research_project.delete()
                return redirect('research_project_list')
            except ProtectedError:
                messages.error(request, "Erro ao tentar excluir o estudo.")

    context = {
        "research_project": research_project,
        "research_project_form": research_project_form,
        "keywords": research_project.keywords.order_by('name'),
        "experiments": research_project.experiment_set.order_by('title')}

    return render(request, template_name, context)


@login_required
@permission_required('experiment.change_researchproject')
def research_project_update(request, research_project_id, template_name="experiment/research_project_register.html"):
    research_project = get_object_or_404(ResearchProject, pk=research_project_id)
    research_project_form = ResearchProjectForm(request.POST or None, instance=research_project)

    if request.method == "POST":
        if request.POST['action'] == "save":
            if research_project_form.is_valid():
                if research_project_form.has_changed():
                    research_project_form.save()
                    messages.success(request, 'Estudo atualizado com sucesso.')
                else:
                    messages.success(request, 'Não há alterações para salvar.')

                redirect_url = reverse("research_project_view", args=(research_project.id,))
                return HttpResponseRedirect(redirect_url)

    context = {
        "research_project": research_project,
        "research_project_form": research_project_form,
        "editing": True}

    return render(request, template_name, context)


@login_required
@permission_required('experiment.change_researchproject')
def keyword_search_ajax(request):
    keywords_name_list = []
    keywords_list_filtered = []
    search_text = None

    if request.method == "POST":
        search_text = request.POST['search_text']

        if search_text:
            # Avoid suggesting the creation of a keyword that already exists.
            keywords_list = Keyword.objects.filter(name__icontains=search_text)
            keywords_name_list = keywords_list.values_list('name', flat=True)
            # Avoid suggestion keywords that are already associated with this research project
            research_project = get_object_or_404(ResearchProject, pk=request.POST['research_project_id'])
            keywords_included = research_project.keywords.values_list('name', flat=True)
            keywords_list_filtered = keywords_list.exclude(name__in=keywords_included).order_by('name')

    return render_to_response('experiment/keyword_ajax_search.html',
                              {'keywords': keywords_list_filtered,
                               'offer_creation': search_text not in keywords_name_list,
                               'research_project_id': request.POST['research_project_id'],
                               'new_keyword_name': search_text})


@login_required
@permission_required('experiment.change_researchproject')
def keyword_create_ajax(request, research_project_id, keyword_name):
    keyword = Keyword.objects.create(name=keyword_name)
    keyword.save()

    research_project = get_object_or_404(ResearchProject, pk=research_project_id)
    research_project.keywords.add(keyword)

    redirect_url = reverse("research_project_view", args=(research_project_id,))
    return HttpResponseRedirect(redirect_url)


@login_required
@permission_required('experiment.change_researchproject')
def keyword_add_ajax(request, research_project_id, keyword_id):
    research_project = get_object_or_404(ResearchProject, pk=research_project_id)
    keyword = get_object_or_404(Keyword, pk=keyword_id)
    research_project.keywords.add(keyword)

    redirect_url = reverse("research_project_view", args=(research_project_id,))
    return HttpResponseRedirect(redirect_url)


def manage_keywords(keyword, research_projects):
    should_remove = True
    for research_project in research_projects:
        if keyword in research_project.keywords.all():
            should_remove = False
            break
    if should_remove:
        keyword.delete()


@login_required
@permission_required('experiment.change_researchproject')
def keyword_remove_ajax(request, research_project_id, keyword_id):
    research_project = get_object_or_404(ResearchProject, pk=research_project_id)
    keyword = get_object_or_404(Keyword, pk=keyword_id)
    research_project.keywords.remove(keyword)

    manage_keywords(keyword, ResearchProject.objects.all())

    redirect_url = reverse("research_project_view", args=(research_project_id,))
    return HttpResponseRedirect(redirect_url)


@login_required
@permission_required('experiment.add_experiment')
def experiment_create(request, research_project_id, template_name="experiment/experiment_register.html"):
    experiment_form = ExperimentForm(request.POST or None, initial={'research_project': research_project_id})

    if request.method == "POST":
        if request.POST['action'] == "save":
            if experiment_form.is_valid():
                experiment_added = experiment_form.save()

                messages.success(request, 'Experimento criado com sucesso.')

                redirect_url = reverse("experiment_view", args=(experiment_added.id,))
                return HttpResponseRedirect(redirect_url)

    context = {
        "research_project": ResearchProject.objects.get(id=research_project_id),
        "experiment_form": experiment_form,
        "creating": True,
        "editing": True}

    return render(request, template_name, context)


@login_required
@permission_required('experiment.change_experiment')
def experiment_view(request, experiment_id, template_name="experiment/experiment_register.html"):
    experiment = get_object_or_404(Experiment, pk=experiment_id)
    group_list = Group.objects.filter(experiment=experiment)
    experiment_form = ExperimentForm(request.POST or None, instance=experiment)

    for field in experiment_form.fields:
        experiment_form.fields[field].widget.attrs['disabled'] = True

    if request.method == "POST":
        if request.POST['action'] == "remove":
            try:
                research_project_id = experiment.research_project_id
                experiment.delete()
                return redirect('research_project_view', research_project_id=research_project_id)
            except ProtectedError:
                messages.error(request, "Não foi possível excluir o experimento, pois há grupos associados")

    context = {
        "research_project": experiment.research_project,
        "experiment_form": experiment_form,
        "group_list": group_list,
        "experiment": experiment}

    return render(request, template_name, context)


@login_required
@permission_required('experiment.change_experiment')
def experiment_update(request, experiment_id, template_name="experiment/experiment_register.html"):
    experiment = get_object_or_404(Experiment, pk=experiment_id)
    group_list = Group.objects.filter(experiment=experiment)
    experiment_form = ExperimentForm(request.POST or None, instance=experiment)

    if request.method == "POST":
        if request.POST['action'] == "save":
            if experiment_form.is_valid():
                if experiment_form.has_changed():
                    experiment_form.save()
                    messages.success(request, 'Experimento atualizado com sucesso.')
                else:
                    messages.success(request, 'Não há alterações para salvar.')

                redirect_url = reverse("experiment_view", args=(experiment_id,))
                return HttpResponseRedirect(redirect_url)

    context = {
        "research_project": experiment.research_project,
        "experiment_form": experiment_form,
        "editing": True,
        "group_list": group_list,
        "experiment": experiment}

    return render(request, template_name, context)


@login_required
def group_create(request, experiment_id, template_name="experiment/group_register.html"):
    experiment = get_object_or_404(Experiment, pk=experiment_id)
    group_form = GroupForm(request.POST or None)

    if request.method == "POST":
        if request.POST['action'] == "save":
            if group_form.is_valid():
                group_added = group_form.save(commit=False)
                group_added.experiment_id = experiment_id
                group_added.save()

                messages.success(request, 'Grupo incluído com sucesso.')

                redirect_url = reverse("group_view", args=(group_added.id,))
                return HttpResponseRedirect(redirect_url)

    context = {
        "group_form": group_form,
        "creating": True,
        "editing": True,
        "experiment": experiment}

    return render(request, template_name, context)


def recursively_create_list_of_questionnaires_and_statistics(block_id,
                                                             list_of_questionnaires_configuration,
                                                             surveys,
                                                             num_participants):
    questionnaire_configurations = ComponentConfiguration.objects.filter(parent_id=block_id,
                                                                         component__component_type="questionnaire")

    for questionnaire_configuration in questionnaire_configurations:
        if questionnaire_configuration.number_of_repetitions is not None:
            fills_per_participant = questionnaire_configuration.number_of_repetitions
            total_fills_needed = num_participants * fills_per_participant
        else:
            fills_per_participant = "Ilimitado"
            total_fills_needed = "Ilimitado"

        subject_responses = QuestionnaireResponse.objects.filter(component_configuration=questionnaire_configuration)
        amount_of_completed_questionnaires = 0

        questionnaire = Questionnaire.objects.get(id=questionnaire_configuration.component.id)

        for subject_response in subject_responses:
            response_result = surveys.get_participant_properties(questionnaire.lime_survey_id,
                                                                 subject_response.token_id, "completed")

            if response_result != "N" and response_result != "":
                amount_of_completed_questionnaires += 1

        list_of_questionnaires_configuration.append({
            "survey_title": surveys.get_survey_title(questionnaire.lime_survey_id),
            "fills_per_participant": fills_per_participant,
            "total_fills_needed": total_fills_needed,
            "total_fills_done": amount_of_completed_questionnaires,
            "id": questionnaire_configuration.id})

    block_configurations = ComponentConfiguration.objects.filter(parent_id=block_id,
                                                                 component__component_type="block")

    for block_configuration in block_configurations:
        list_of_questionnaires_configuration = recursively_create_list_of_questionnaires_and_statistics(
            Block.objects.get(id=block_configuration.component.id),
            list_of_questionnaires_configuration,
            surveys,
            num_participants)

    return list_of_questionnaires_configuration



@login_required
@permission_required('experiment.add_experiment')
def group_view(request, group_id, template_name="experiment/group_register.html"):
    group = get_object_or_404(Group, pk=group_id)
    group_form = GroupForm(request.POST or None, instance=group)

    for field in group_form.fields:
        group_form.fields[field].widget.attrs['disabled'] = True

    experiment = get_object_or_404(Experiment, pk=group.experiment_id)

    # Navigate the components of the experimental protocol from the root to see if there is any questionnaire component
    # in this group.
    if group.experimental_protocol is not None:
        surveys = Questionnaires()
        # This method shows a message to the user if limesurvey is not available.
        check_limesurvey_access(request, surveys)

        list_of_questionnaires_configuration = recursively_create_list_of_questionnaires_and_statistics(
            group.experimental_protocol,
            [],
            surveys,
            SubjectOfGroup.objects.filter(group_id=group_id).count())

        surveys.release_session_key()
    else:
        list_of_questionnaires_configuration = None

    if request.method == "POST":
        if request.POST['action'] == "remove":
            try:
                group.delete()
                redirect_url = reverse("experiment_view", args=(experiment.id,))
                return HttpResponseRedirect(redirect_url)
            except ProtectedError:
                messages.error(request, "Não foi possível excluir o grupo, pois há dependências.")
        elif request.POST['action'] == "remove_experimental_protocol":
            group.experimental_protocol = None
            group.save()

    context = {
        "classification_of_diseases_list": group.classification_of_diseases.all(),
        "group_form": group_form,
        "questionnaires_configuration_list": list_of_questionnaires_configuration,
        "experiment": experiment,
        "group": group,
        "editing": False,
        "number_of_subjects": SubjectOfGroup.objects.all().filter(group=group).count()
    }

    return render(request, template_name, context)


@login_required
@permission_required('experiment.add_experiment')
def group_update(request, group_id, template_name="experiment/group_register.html"):
    group = get_object_or_404(Group, pk=group_id)
    group_form = GroupForm(request.POST or None, instance=group)
    experiment = get_object_or_404(Experiment, pk=group.experiment_id)

    if request.method == "POST":
        if request.POST['action'] == "save":
            if group_form.is_valid():
                if group_form.has_changed():
                    group_form.save()
                    messages.success(request, 'Grupo atualizado com sucesso.')
                else:
                    messages.success(request, 'Não há alterações para salvar.')

                redirect_url = reverse("group_view", args=(group_id,))
                return HttpResponseRedirect(redirect_url)

    context = {
        "group_form": group_form,
        "editing": True,
        "experiment": experiment,
        "group": group,
    }

    return render(request, template_name, context)


@permission_required('experiment.add_subject')
def search_cid10_ajax(request):
    cid_10_list = ''

    if request.method == "POST":
        search_text = request.POST['search_text']
        group_id = request.POST['group_id']

        if search_text:
            cid_10_list = ClassificationOfDiseases.objects.filter(Q(abbreviated_description__icontains=search_text) |
                                                                  Q(description__icontains=search_text))

        return render_to_response('experiment/ajax_cid10.html', {'cid_10_list': cid_10_list, 'group_id': group_id})


@login_required
@permission_required('experiment.add_experiment')
def classification_of_diseases_insert(request, group_id, classification_of_diseases_id):
    """Add group disease"""
    group = get_object_or_404(Group, pk=group_id)
    classification_of_diseases = get_object_or_404(ClassificationOfDiseases, pk=classification_of_diseases_id)
    group.classification_of_diseases.add(classification_of_diseases)
    redirect_url = reverse("group_view", args=(group_id,))
    return HttpResponseRedirect(redirect_url)


@login_required
@permission_required('experiment.add_experiment')
def classification_of_diseases_remove(request, group_id, classification_of_diseases_id):
    """Remove group disease"""
    group = get_object_or_404(Group, pk=group_id)
    classification_of_diseases = get_object_or_404(ClassificationOfDiseases, pk=classification_of_diseases_id)
    classification_of_diseases.group_set.remove(group)
    redirect_url = reverse("group_view", args=(group_id,))
    return HttpResponseRedirect(redirect_url)


@login_required
@permission_required('experiment.change_questionnaireconfiguration')
def questionnaire_view(request, group_id, component_configuration_id,
                         template_name="experiment/questionnaire_view.html"):
    questionnaire_configuration = get_object_or_404(ComponentConfiguration, pk=component_configuration_id)
    group = get_object_or_404(Group, pk=group_id)
    questionnaire = Questionnaire.objects.get(id=questionnaire_configuration.component.id)

    surveys = Questionnaires()
    questionnaire_title = surveys.get_survey_title(
        Questionnaire.objects.get(id=questionnaire_configuration.component_id).lime_survey_id)

    limesurvey_available = check_limesurvey_access(request, surveys)

    subject_list_with_status = []

    for subject_of_group in SubjectOfGroup.objects.filter(group=group).order_by('subject__patient__name'):
        subject_responses = QuestionnaireResponse.objects.\
            filter(subject_of_group=subject_of_group,
                   component_configuration=questionnaire_configuration)
        amount_of_completed_questionnaires = 0
        questionnaire_responses_with_status = []

        for subject_response in subject_responses:
            response_result = surveys.get_participant_properties(questionnaire.lime_survey_id,
                                                                 subject_response.token_id, "completed")
            completed = False

            if response_result != "N" and response_result != "":
                amount_of_completed_questionnaires += 1
                completed = True

            questionnaire_responses_with_status.append(
                {'questionnaire_response': subject_response,
                 'completed': completed}
            )

        # If unlimited fills, percentage is related to the number of completed questionnaires
        if questionnaire_configuration.number_of_repetitions is None:
            denominator = subject_responses.count()

            if subject_responses.count() > 0:
                percentage = 100 * amount_of_completed_questionnaires / denominator
            else:
                percentage = 0
        else:
            denominator = questionnaire_configuration.number_of_repetitions

            # Handle cases in which number of possible responses was reduced afterwords.
            if questionnaire_configuration.number_of_repetitions < amount_of_completed_questionnaires:
                percentage = 100
            else:
                percentage = 100 * amount_of_completed_questionnaires / denominator

        subject_list_with_status.append(
            {'subject': subject_of_group.subject,
             'amount_of_completed_questionnaires': amount_of_completed_questionnaires,
             'denominator': denominator,
             'percentage': percentage,
             'questionnaire_responses': questionnaire_responses_with_status})

    surveys.release_session_key()

    context = {
        "group": group,
        "questionnaire_title": questionnaire_title,
        "questionnaire_configuration": questionnaire_configuration,
        'subject_list': subject_list_with_status,
        "limesurvey_available": limesurvey_available
    }

    return render(request, template_name, context)


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


@login_required
@permission_required('experiment.add_subject')
def subjects(request, group_id, template_name="experiment/subjects.html"):
    group = get_object_or_404(Group, id=group_id)

    subject_list_with_status = []
    surveys = Questionnaires()
    limesurvey_available = check_limesurvey_access(request, surveys)

    # Navigate the components of the experimental protocol from the root to see if there is any questionnaire component
    # in this group.
    if group.experimental_protocol is not None:
        list_of_questionnaires_configuration = recursively_create_list_of_questionnaires(group.experimental_protocol,
                                                                                         [])

        # For each subject of the group...
        for subject_of_group in SubjectOfGroup.objects.filter(group=group).order_by('subject__patient__name'):
            number_of_questionnaires_filled = 0

            # For each questionnaire in the experimental protocol of the group...
            for questionnaire_configuration in list_of_questionnaires_configuration:
                # Get the responses
                subject_responses = QuestionnaireResponse.objects. \
                    filter(subject_of_group=subject_of_group, component_configuration=questionnaire_configuration)

                # This is a shortcut that allows to avid the delay of the connection to LimeSurvey.
                if (questionnaire_configuration.number_of_repetitions is None and subject_responses.count() > 0) or \
                        (questionnaire_configuration.number_of_repetitions is not None and
                            subject_responses.count() >= questionnaire_configuration.number_of_repetitions):

                    # Count the number of completed responses
                    amount_of_completed_responses = 0

                    for subject_response in subject_responses:
                        # Check if completed
                        response_result = surveys.get_participant_properties(
                            Questionnaire.objects.get(id=questionnaire_configuration.component.id).lime_survey_id,
                            subject_response.token_id, "completed")

                        if response_result == "N" or response_result == "":
                            # If there is an incomplete response for a questionnaire, this questionnaire is counted
                            # as not completed.
                            amount_of_completed_responses = 0
                            break
                        else:
                            amount_of_completed_responses += 1

                    # Count this questionnaire as completed if it is unlimited and has at least one completed
                    # response, or it is limited and the amount of completed response is greater than or equal to
                    # the number of expected responses.
                    if (questionnaire_configuration.number_of_repetitions is None and
                            amount_of_completed_responses > 0) or \
                            (questionnaire_configuration.number_of_repetitions is not None and
                                amount_of_completed_responses >= questionnaire_configuration.number_of_repetitions):
                        number_of_questionnaires_filled += 1

            percentage = 0

            if len(list_of_questionnaires_configuration) > 0:
                percentage = 100 * number_of_questionnaires_filled / len(list_of_questionnaires_configuration)

            subject_list_with_status.append(
                {'subject': subject_of_group.subject,
                 'number_of_questionnaires_filled': number_of_questionnaires_filled,
                 'total_of_questionnaires': len(list_of_questionnaires_configuration),
                 'percentage': percentage,
                 'consent': subject_of_group.consent_form})

    surveys.release_session_key()

    context = {
        'group': group,
        'subject_list': subject_list_with_status,
        "limesurvey_available": limesurvey_available
    }

    return render(request, template_name, context)


def subject_questionnaire_response_start_fill_questionnaire(request, subject_id, group_id, questionnaire_id):
    questionnaire_response_form = QuestionnaireResponseForm(request.POST)

    if questionnaire_response_form.is_valid():
        questionnaire_response = questionnaire_response_form.save(commit=False)
        questionnaire_config = get_object_or_404(ComponentConfiguration, id=questionnaire_id)
        questionnaire_lime_survey = Questionnaires()
        subject = get_object_or_404(Subject, pk=subject_id)
        patient = subject.patient
        subject_of_group = get_object_or_404(SubjectOfGroup, subject=subject, group_id=group_id)
        lime_survey_id = Questionnaire.objects.get(id=questionnaire_config.component_id).lime_survey_id

        if not questionnaire_lime_survey.survey_has_token_table(lime_survey_id):
            messages.warning(request, 'Preenchimento não disponível - Tabela de tokens não iniciada')
            return None, None

        if questionnaire_lime_survey.get_survey_properties(lime_survey_id, 'active') == 'N':
            messages.warning(request, 'Preenchimento não disponível - Questionário não está ativo')
            return None, None

        if not check_required_fields(questionnaire_lime_survey, lime_survey_id):
            messages.warning(request, 'Preenchimento não disponível - Questionário não contém campos padronizados')
            return None, None

        result = questionnaire_lime_survey.add_participant(lime_survey_id, patient.name, '', patient.email)

        questionnaire_lime_survey.release_session_key()

        if not result:
            messages.warning(request,
                             'Falha ao gerar token para responder questionário. Verifique se o questionário está ativo')
            return None, None

        questionnaire_response.subject_of_group = subject_of_group
        questionnaire_response.component_configuration = questionnaire_config
        questionnaire_response.token_id = result['token_id']
        questionnaire_response.date = datetime.datetime.strptime(request.POST['date'], '%d/%m/%Y')
        questionnaire_response.questionnaire_responsible = request.user
        questionnaire_response.save()

        redirect_url = get_limesurvey_response_url(questionnaire_response)

        return redirect_url, questionnaire_response.pk
    else:
        return None, None


def get_limesurvey_response_url(questionnaire_response):
    questionnaire = Questionnaire.objects.get(id=questionnaire_response.component_configuration.component.id)

    questionnaire_lime_survey = Questionnaires()
    token = questionnaire_lime_survey.get_participant_properties(questionnaire.lime_survey_id,
                                                                 questionnaire_response.token_id, "token")
    questionnaire_lime_survey.release_session_key()

    redirect_url = \
        '%s/index.php/%s/token/%s/responsibleid/%s/acquisitiondate/%s/subjectid/%s/newtest/Y' % (
            settings.LIMESURVEY['URL_WEB'],
            questionnaire.lime_survey_id,
            token,
            str(questionnaire_response.questionnaire_responsible.id),
            questionnaire_response.date.strftime('%d-%m-%Y'),
            str(questionnaire_response.subject_of_group.subject.id))

    return redirect_url


@login_required
@permission_required('experiment.add_questionnaireresponse')
def subject_questionnaire_response_create(request, group_id, subject_id, questionnaire_id,
                                          template_name="experiment/subject_questionnaire_response_form.html"):
    questionnaire_config = get_object_or_404(ComponentConfiguration, id=questionnaire_id)
    group = get_object_or_404(Group, id=group_id)

    surveys = Questionnaires()
    lime_survey_id = Questionnaire.objects.get(id=questionnaire_config.component_id).lime_survey_id
    survey_title = surveys.get_survey_title(lime_survey_id)
    survey_active = surveys.get_survey_properties(lime_survey_id, 'active')
    # survey_admin = surveys.get_survey_properties(questionnaire_config.lime_survey_id, 'admin')
    surveys.release_session_key()

    questionnaire_response_form = None
    fail = None
    redirect_url = None
    questionnaire_response_id = None

    questionnaire_response_form = QuestionnaireResponseForm(request.POST or None)

    if request.method == "POST":
        if request.POST['action'] == "save":
            redirect_url, questionnaire_response_id = \
                subject_questionnaire_response_start_fill_questionnaire(request, subject_id, group_id, questionnaire_id)
            if not redirect_url:
                fail = True
            else:
                fail = False
                messages.info(request, 'Você será redirecionado para o questionário. Aguarde.')

    origin = get_origin(request)

    context = {
        "FAIL": fail,
        "URL": redirect_url,
        "questionnaire_response_id": questionnaire_response_id,
        "questionnaire_response_form": questionnaire_response_form,
        "questionnaire_configuration": questionnaire_config,
        "survey_title": survey_title,
        # "survey_admin": survey_admin,
        "survey_active": survey_active,
        "questionnaire_responsible": request.user.get_username(),
        "creating": True,
        "subject": get_object_or_404(Subject, pk=subject_id),
        "group": group,
        "origin": origin
    }

    return render(request, template_name, context)


@login_required
@permission_required('experiment.change_questionnaireresponse')
def questionnaire_response_update(request, questionnaire_response_id,
                                  template_name="experiment/subject_questionnaire_response_form.html"):
    questionnaire_response = get_object_or_404(QuestionnaireResponse, id=questionnaire_response_id)

    questionnaire = Questionnaire.objects.get(id=questionnaire_response.component_configuration.component.id)
    group = Group.objects.get(id=questionnaire_response.subject_of_group.group_id)

    surveys = Questionnaires()
    survey_title = surveys.get_survey_title(questionnaire.lime_survey_id)
    survey_active = surveys.get_survey_properties(questionnaire.lime_survey_id, 'active')
    survey_completed = (surveys.get_participant_properties(questionnaire.lime_survey_id,
                                                           questionnaire_response.token_id,
                                                           "completed") != "N")
    surveys.release_session_key()

    subject = questionnaire_response.subject_of_group.subject

    questionnaire_response_form = QuestionnaireResponseForm(None, instance=questionnaire_response)

    fail = None
    redirect_url = None

    if request.method == "POST":
        if request.POST['action'] == "save":
            redirect_url = get_limesurvey_response_url(questionnaire_response)

            if not redirect_url:
                fail = True
            else:
                fail = False
                messages.info(request, 'Você será redirecionado para o questionário. Aguarde.')

        elif request.POST['action'] == "remove":
            surveys = Questionnaires()
            result = surveys.delete_participant(
                questionnaire.lime_survey_id,
                questionnaire_response.token_id)
            surveys.release_session_key()

            can_delete = False

            if str(questionnaire_response.token_id) in result:
                result = result[str(questionnaire_response.token_id)]
                if result == 'Deleted' or result == 'Invalid token ID':
                    can_delete = True
            else:
                if 'status' in result and result['status'] == u'Error: Invalid survey ID':
                    can_delete = True

            if can_delete:
                questionnaire_response.delete()
                messages.success(request, 'Preenchimento removido com sucesso')
            else:
                messages.error(request, "Erro ao deletar o preenchimento")

            redirect_url = reverse("subject_questionnaire", args=(group.id, subject.id,))
            return HttpResponseRedirect(redirect_url)

    origin = get_origin(request)

    context = {
        "FAIL": fail,
        "URL": redirect_url,
        "questionnaire_response_form": questionnaire_response_form,
        "questionnaire_configuration": questionnaire_response.component_configuration,
        "survey_title": survey_title,
        "survey_active": survey_active,
        "questionnaire_response_id": questionnaire_response_id,
        "questionnaire_responsible": questionnaire_response.questionnaire_responsible,
        "creating": False,
        "subject": subject,
        "completed": survey_completed,
        "group": group,
        "origin": origin
    }

    return render(request, template_name, context)


def get_origin(request):
    origin = '0'

    # origin is in request.GET also when the request is a post!
    if 'origin' in request.GET:
        origin = request.GET['origin']

    return origin


def check_required_fields(surveys, lime_survey_id):
    """
    método para verificar se o questionário tem as questões de identificação corretas
    e se seus tipos também são corretos
    """

    fields_to_validate = {
        'responsibleid': {'type': 'N', 'found': False},
        'acquisitiondate': {'type': 'D', 'found': False},
        'subjectid': {'type': 'N', 'found': False},
    }

    validated_quantity = 0
    error = False

    groups = surveys.list_groups(lime_survey_id)

    if 'status' not in groups:

        for group in groups:
            question_list = surveys.list_questions(lime_survey_id, group['id'])
            for question in question_list:
                question_properties = surveys.get_question_properties(question, None)
                if question_properties['title'] in fields_to_validate:
                    field = fields_to_validate[question_properties['title']]
                    if not field['found']:
                        field['found'] = True
                        if field['type'] == question_properties['type']:
                            validated_quantity += 1
                        else:
                            error = True
                if error or validated_quantity == len(fields_to_validate):
                    break
            if error or validated_quantity == len(fields_to_validate):
                break

    return validated_quantity == len(fields_to_validate)


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

                if isinstance(question['answer_options'], basestring) and question[
                    'answer_options'] == "super_question":

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


@login_required
@permission_required('experiment.view_questionnaireresponse')
def questionnaire_response_view(request, questionnaire_response_id,
                                template_name="experiment/subject_questionnaire_response_view.html"):
    origin = get_origin(request)

    status_mode = None

    if 'status' in request.GET:
        status_mode = request.GET['status']

    questionnaire_response = get_object_or_404(QuestionnaireResponse, id=questionnaire_response_id)
    questionnaire_configuration = questionnaire_response.component_configuration
    questionnaire = Questionnaire.objects.get(id=questionnaire_configuration.component.id)
    lime_survey_id = questionnaire.lime_survey_id
    token_id = questionnaire_response.token_id
    language_code = request.LANGUAGE_CODE

    # Get the responses for each question of the questionnaire.
    survey_title, questionnaire_responses = get_questionnaire_responses(language_code, lime_survey_id, token_id)

    context = {
        "group": questionnaire_response.subject_of_group.group,
        "questionnaire_response": questionnaire_response,
        "questionnaire_responses": questionnaire_responses,
        "status_mode": status_mode,
        "subject": questionnaire_response.subject_of_group.subject,
        "survey_title": survey_title,
        "origin": origin,
    }

    return render(request, template_name, context)


@login_required
# TODO: associate the right permission
# @permission_required('patient.add_medicalrecorddata')
def patient_questionnaire_response_view(request, patient_questionnaire_response_id,
                                        template_name="experiment/subject_questionnaire_response_view.html"):

    origin = get_origin(request)

    status_mode = None

    if 'status' in request.GET:
        status_mode = request.GET['status']

    patient_questionnaire_response = get_object_or_404(PatientQuestionnaireResponse,
                                                       id=patient_questionnaire_response_id)

    lime_survey_id = patient_questionnaire_response.questionnaire.lime_survey_id
    token_id = patient_questionnaire_response.token_id
    language_code = request.LANGUAGE_CODE

    survey_title, questionnaire_responses = get_questionnaire_responses(language_code, lime_survey_id, token_id)

    context = {
        "questionnaire_responses": questionnaire_responses,
        "survey_title": survey_title,
        "patient_questionnaire_response": patient_questionnaire_response,
        "origin": origin,
        "status_mode": status_mode
    }

    return render(request, template_name, context)


def check_limesurvey_access(request, surveys):
    limesurvey_available = True
    if not surveys.session_key:
        limesurvey_available = False
        messages.warning(request, "LimeSurvey indisponível. Sistema funcionando parcialmente.")

    return limesurvey_available


@login_required
@permission_required('experiment.view_questionnaireresponse')
def subject_questionnaire_view(request, group_id, subject_id,
                               template_name="experiment/subject_questionnaire_response_list.html"):
    group = get_object_or_404(Group, id=group_id)
    subject = get_object_or_404(Subject, id=subject_id)

    subject_questionnaires = []
    can_remove = True

    surveys = Questionnaires()
    limesurvey_available = check_limesurvey_access(request, surveys)

    list_of_questionnaires_configuration = recursively_create_list_of_questionnaires(group.experimental_protocol,
                                                                                     [])
    subject_of_group = get_object_or_404(SubjectOfGroup, group=group, subject=subject)

    for questionnaire_configuration in list_of_questionnaires_configuration:
        questionnaire_responses = QuestionnaireResponse.objects. \
            filter(subject_of_group=subject_of_group, component_configuration=questionnaire_configuration)

        questionnaire_responses_with_status = []

        # If any questionnaire has responses, the subject can't be removed from the group.
        if questionnaire_responses.count() > 0:
            can_remove = False

        questionnaire = Questionnaire.objects.get(id=questionnaire_configuration.component.id)

        for questionnaire_response in questionnaire_responses:
            response_result = surveys.get_participant_properties(questionnaire.lime_survey_id,
                                                                 questionnaire_response.token_id,
                                                                 "completed")
            questionnaire_responses_with_status.append(
                {'questionnaire_response': questionnaire_response,
                 'completed': None if response_result is None else response_result != "N" and response_result != ""}
            )

        subject_questionnaires.append(
            {'questionnaire_configuration': questionnaire_configuration,
             'title': surveys.get_survey_title(questionnaire.lime_survey_id),
             'questionnaire_responses': questionnaire_responses_with_status}
        )

    if request.method == "POST":
        if request.POST['action'] == "remove":
            if can_remove:
                get_object_or_404(SubjectOfGroup, group=group, subject=subject).delete()

                messages.info(request, 'Participante removido do experimento.')
                redirect_url = reverse("subjects", args=(group_id,))
                return HttpResponseRedirect(redirect_url)
            else:
                messages.error(request, "Não foi possível excluir o participante, pois há respostas associadas")
                redirect_url = reverse("subject_questionnaire", args=(group_id, subject_id,))
                return HttpResponseRedirect(redirect_url)

    context = {
        'subject': subject,
        'group': group,
        'subject_questionnaires': subject_questionnaires,
        'limesurvey_available': limesurvey_available
    }

    surveys.release_session_key()

    return render(request, template_name, context)


@login_required
@permission_required('experiment.add_subject')
def subjects_insert(request, group_id, patient_id):
    patient = get_object_or_404(Patient, pk=patient_id)

    subject = Subject()

    try:
        subject = Subject.objects.get(patient=patient)
    except subject.DoesNotExist:
        subject.patient = patient
        subject.save()

    group = get_object_or_404(Group, id=group_id)

    if not SubjectOfGroup.objects.all().filter(group=group, subject=subject):
        SubjectOfGroup(subject=subject, group=group).save()
    else:
        messages.warning(request, 'Participante já inserido para este grupo.')

    redirect_url = reverse("subjects", args=(group_id,))
    return HttpResponseRedirect(redirect_url)


@login_required
@permission_required('experiment.add_subject')
def search_patients_ajax(request):
    patient_list = ''
    if request.method == "POST":
        search_text = request.POST['search_text']
        group_id = request.POST['group_id']
        if search_text:
            if re.match('[a-zA-Z ]+', search_text):
                patient_list = \
                    Patient.objects.filter(name__icontains=search_text).exclude(removed=True).order_by('name')
            else:
                patient_list = \
                    Patient.objects.filter(cpf__icontains=search_text).exclude(removed=True).order_by('name')

        return render_to_response('experiment/ajax_search_patients.html',
                                  {'patients': patient_list, 'group_id': group_id})


def upload_file(request, subject_id, group_id, template_name="experiment/upload_consent_form.html"):
    subject = get_object_or_404(Subject, pk=subject_id)
    group = get_object_or_404(Group, pk=group_id)
    subject_of_group = get_object_or_404(SubjectOfGroup, subject=subject, group=group)

    file_form = None

    if request.method == "POST":
        if request.POST['action'] == "upload":
            file_form = FileForm(request.POST, request.FILES, instance=subject_of_group)
            if 'consent_form' in request.FILES:
                if file_form.is_valid():
                    file_form.save()
                    messages.success(request, 'Termo salvo com sucesso.')

                redirect_url = reverse("subjects", args=(group_id, ))
                return HttpResponseRedirect(redirect_url)
            else:
                messages.error(request, 'Não existem anexos para salvar')
        elif request.POST['action'] == "remove":
                subject_of_group.consent_form.delete()
                subject_of_group.save()
                messages.success(request, 'Anexo removido com sucesso.')

                redirect_url = reverse("subjects", args=(group_id,))
                return HttpResponseRedirect(redirect_url)

    else:
        file_form = FileForm(request.POST or None)

    context = {
        'subject': subject,
        'group': group,
        'file_form': file_form,
        'file_list': subject_of_group.consent_form
    }
    return render(request, template_name, context)


@login_required
@permission_required('experiment.view_experiment')
def component_list(request, experiment_id, template_name="experiment/component_list.html"):
    experiment = get_object_or_404(Experiment, pk=experiment_id)

    # As it is not possible to sort_by get_component_type_display, filter without sorting and sort later.
    components = Component.objects.filter(experiment=experiment)

    # Create a temporary list of tuples from the query_set to be able to sort by get_component_type_display,
    # identification and name.
    temp_list_of_tuples = []

    for component in components:
        temp_list_of_tuples.append((component,
                                    component.get_component_type_display(),
                                    component.identification))

    temp_list_of_tuples.sort(key=itemgetter(1, 2))

    # Reduce the complexity by creating list of component configurations without having tuples.
    components = []

    for tuple in temp_list_of_tuples:
        components.append(tuple[0])

    for component in components:
        component.icon_class = icon_class[component.component_type]

    component_type_choices = []

    for type, type_name in Component.COMPONENT_TYPES:
        component_type_choices.append((type, type_name, icon_class.get(type)))

    context = {
        "experiment": experiment,
        "component_list": components,
        "component_type_choices": component_type_choices
    }

    return render(request, template_name, context)


@login_required
@permission_required('experiment.change_experiment')
def component_change_the_order(request, path_of_the_components, configuration_id, command):
    component_configuration = get_object_or_404(ComponentConfiguration, pk=configuration_id)
    component = get_object_or_404(Component, pk=component_configuration.parent_id)

    component_configuration_to_exchange = ComponentConfiguration.objects.filter(parent_id=component.id)
    if command == "down":
        component_configuration_to_exchange = component_configuration_to_exchange.filter(
            order__gt=component_configuration.order).order_by('order')
    else:
        component_configuration_to_exchange = component_configuration_to_exchange.filter(
            order__lt=component_configuration.order).order_by('-order')
    component_configuration_to_exchange = component_configuration_to_exchange[0]

    configuration_order = component_configuration.order
    configuration_to_exchange_order = component_configuration_to_exchange.order
    last_configuration = ComponentConfiguration.objects.filter(
        parent=component_configuration.parent).order_by('-order').first()

    component_configuration_to_exchange.order = last_configuration.order + 1
    component_configuration_to_exchange.save()

    component_configuration.order = configuration_to_exchange_order
    component_configuration.save()

    component_configuration_to_exchange.order = configuration_order
    component_configuration_to_exchange.save()

    redirect_url = reverse("component_view", args=(path_of_the_components,))

    return HttpResponseRedirect(redirect_url)


@login_required
@permission_required('experiment.change_experiment')
def component_create(request, experiment_id, component_type):
    template_name = "experiment/" + component_type + "_component.html"

    experiment = get_object_or_404(Experiment, pk=experiment_id)
    component_form = ComponentForm(request.POST or None)
    # This is needed for the form to be able to validate the presence of a duration in a pause component only.
    component_form.component_type = component_type
    questionnaires_list = []
    specific_form = None

    if component_type == 'instruction':
        specific_form = InstructionForm(request.POST or None)
    elif component_type == 'stimulus':
        specific_form = StimulusForm(request.POST or None)
    elif component_type == 'questionnaire':
        questionnaires_list = Questionnaires().find_all_active_questionnaires()
    elif component_type == 'block':
        specific_form = BlockForm(request.POST or None, initial={'number_of_mandatory_components': None})
        # component_form.fields['duration_value'].widget.attrs['disabled'] = True
        # component_form.fields['duration_unit'].widget.attrs['disabled'] = True

    if request.method == "POST":
        new_specific_component = None

        if component_form.is_valid():
            if component_type == 'questionnaire':
                new_specific_component = Questionnaire()
                new_specific_component.lime_survey_id = request.POST['questionnaire_selected']
            elif component_type == 'pause':
                new_specific_component = Pause()
            elif component_type == 'task':
                new_specific_component = Task()
            elif component_type == 'task_experiment':
                new_specific_component = TaskForTheExperimenter()
            elif specific_form.is_valid():
                new_specific_component = specific_form.save(commit=False)

            if new_specific_component is not None:
                component = component_form.save(commit=False)
                new_specific_component.description = component.description
                new_specific_component.identification = component.identification
                new_specific_component.component_type = component_type
                new_specific_component.experiment = experiment
                new_specific_component.duration_value = component.duration_value
                new_specific_component.duration_unit = component.duration_unit
                new_specific_component.save()

                messages.success(request, 'Passo incluído com sucesso.')

                if component_type == 'block':
                    redirect_url = reverse("component_view", args=(new_specific_component.id,))
                else:
                    redirect_url = reverse("component_list", args=(experiment_id,))
                return HttpResponseRedirect(redirect_url)

    context = {
        "back_cancel_url": "/experiment/" + str(experiment.id) + "/components",
        "component_form": component_form,
        "creating": True,
        "experiment": experiment,
        "questionnaires_list": questionnaires_list,
        "specific_form": specific_form,
    }
    return render(request, template_name, context)


def create_list_of_breadcrumbs(list_of_ids_of_components_and_configurations):
    # Create a list of components or component configurations to be able to show the breadcrumb.
    list_of_breadcrumbs = []

    for idx, id_item in enumerate(list_of_ids_of_components_and_configurations):
        if id_item[0] != "G":
            if id_item[0] == "U":  # If id_item starts with 'U' (from 'use'), it is a configuration.
                cc = get_object_or_404(ComponentConfiguration, pk=id_item[1:])

                if cc.name is not None and cc.name != "":
                    name = cc.name
                else:
                    name = "Uso do passo " + cc.component.identification

                view_name = "component_edit"
            else:
                c = get_object_or_404(Component, pk=id_item)
                name = c.identification
                view_name = "component_view"

            list_of_breadcrumbs.append({
                "name": name, "url":
                reverse(view_name, args=(delimiter.join(list_of_ids_of_components_and_configurations[:idx+1]),))})

    return list_of_breadcrumbs


def create_back_cancel_url(component_type, component_configuration, path_of_the_components,
                           list_of_ids_of_components_and_configurations, experiment, updating):
    if component_type == "block" and component_configuration is None and updating:
        # Return to the screen for viewing a block
        back_cancel_url = "/experiment/component/" + path_of_the_components
    elif len(list_of_ids_of_components_and_configurations) > 1:
        # There is a parent. Remove the current element from the path so that the parent is shown.
        path_without_last = path_of_the_components[:path_of_the_components.rfind("-")]
        last_hyphen_index = path_without_last.rfind("-")

        if last_hyphen_index == -1:
            parent = path_without_last
        else:
            parent = path_without_last[last_hyphen_index + 1:]

        if parent[0] == "G":
            back_cancel_url = "/experiment/group/" + parent[1:]
        else:
            if parent[0] == "U":
                parent = ComponentConfiguration.objects.get(id=parent[1:]).component

            # if parent is block:
            if Block.objects.filter(pk=parent).exists():
                back_cancel_url = "/experiment/component/" + path_without_last
            else:
                back_cancel_url = "/experiment/component/edit/" + path_without_last
    else:
        # Return to the lis of components
        back_cancel_url = "/experiment/" + str(experiment.id) + "/components"

    return back_cancel_url


second_in_milliseconds = 1000
minute_in_milliseconds = 60 * second_in_milliseconds
hour_in_milliseconds = 60 * minute_in_milliseconds
day_in_milliseconds = 24 * hour_in_milliseconds
week_in_milliseconds = 7 * day_in_milliseconds
month_in_milliseconds = 30 * day_in_milliseconds
year_in_milliseconds = 365 * day_in_milliseconds

def convert_to_milliseconds(value, unit):
    if value is None:
        return 0
    else:
        if unit == 'y':
            return value * year_in_milliseconds
        if unit == 'mon':
            return value * month_in_milliseconds
        if unit == 'w':
            return value * week_in_milliseconds
        if unit == 'd':
            return value * day_in_milliseconds
        if unit == 'h':
            return value * hour_in_milliseconds
        if unit == 'min':
            return value * minute_in_milliseconds
        if unit == 's':
            return value * second_in_milliseconds
        if unit == 'ms':
            return value
        else:  # Unit is None or unknown
            return 0


def convert_to_string(duration_in_milliseconds):
    string = ""

    duration_in_years = int(duration_in_milliseconds / year_in_milliseconds)
    if duration_in_years >= 1:
        string += str(duration_in_years) + (" anos " if duration_in_years > 1 else " ano ")
        duration_in_milliseconds -= duration_in_years * year_in_milliseconds

    duration_in_months = int(duration_in_milliseconds / month_in_milliseconds)
    if duration_in_months >= 1:
        string += str(duration_in_months) + (" meses " if duration_in_months > 1 else " mês ")
        duration_in_milliseconds -= duration_in_months * month_in_milliseconds

    duration_in_weeks = int(duration_in_milliseconds / week_in_milliseconds)
    if duration_in_weeks >= 1:
        string += str(duration_in_weeks) + (" semanas " if duration_in_weeks > 1 else " semana ")
        duration_in_milliseconds -= duration_in_weeks * week_in_milliseconds

    duration_in_days = int(duration_in_milliseconds / day_in_milliseconds)
    if duration_in_days >= 1:
        string += str(duration_in_days) + (" dias " if duration_in_days > 1 else " dia ")
        duration_in_milliseconds -= duration_in_days * day_in_milliseconds

    duration_in_hours = int(duration_in_milliseconds / hour_in_milliseconds)
    if duration_in_hours >= 1:
        string += str(duration_in_hours) + (" horas " if duration_in_hours > 1 else " hora ")
        duration_in_milliseconds -= duration_in_hours * hour_in_milliseconds

    duration_in_minutes = int(duration_in_milliseconds / minute_in_milliseconds)
    if duration_in_minutes >= 1:
        string += str(duration_in_minutes) + (" minutos " if duration_in_minutes > 1 else " minuto ")
        duration_in_milliseconds -= duration_in_minutes * minute_in_milliseconds

    duration_in_seconds = int(duration_in_milliseconds / second_in_milliseconds)
    if duration_in_seconds >= 1:
        string += str(duration_in_seconds) + (" segundos " if duration_in_seconds > 1 else " segundo ")
        duration_in_milliseconds -= duration_in_seconds * second_in_milliseconds

    if duration_in_milliseconds >= 1:
        string += str(duration_in_milliseconds) +\
                  (" milissegundos " if duration_in_milliseconds > 1 else " milissegundo ")

    if string == "":
        string = "0"
    else:
        # Add commas and 'and' to the string
        list_of_words = string.split(" ")
        values = list_of_words[::2]
        units =  list_of_words[1::2]
        list_of_values_with_units = [value + " " + unit for value, unit in zip(values, units)]
        before_and = ", ".join(list_of_values_with_units[0:-1])

        if before_and == "":
            string = list_of_values_with_units[-1]
        else:
            string = before_and + " e " + list_of_values_with_units[-1]

    return string

def calculate_block_duration(block):
    duration_value_in_milliseconds = 0

    for component_configuration in block.children.all():
        component = component_configuration.component

        if component.component_type == 'block':
            component_duration = calculate_block_duration(Block.objects.get(id=component.id))
        else:
            component_duration = convert_to_milliseconds(component.duration_value, component.duration_unit)

        if block.type == Block.SEQUENCE:
            # Add duration of the children
            duration_value_in_milliseconds += component_duration
        elif block.type == Block.PARALLEL_BLOCK:
            # Duration of the block is the duration of the longest child.
            if component_duration > duration_value_in_milliseconds:
                duration_value_in_milliseconds = component_duration


    return duration_value_in_milliseconds


def access_objects_for_view_and_update(request, path_of_the_components, updating=False):
    list_of_ids_of_components_and_configurations = path_of_the_components.split(delimiter)

    # The last id of the list is the one that we want to show.
    id = list_of_ids_of_components_and_configurations[-1]

    group = None

    if path_of_the_components[0] == "G":
        # The id of the group comes after "G"
        group_id = int(list_of_ids_of_components_and_configurations[0][1:])
        group = get_object_or_404(Group, pk=group_id)

    component_configuration = None
    configuration_form = None

    if id[0] == "U":  # If id starts with 'U' (from 'use'), it is a configuration.
        component_configuration = get_object_or_404(ComponentConfiguration, pk=id[1:])
        configuration_form = ComponentConfigurationForm(request.POST or None, instance=component_configuration)
        component = component_configuration.component
    else:
        component = get_object_or_404(Component, pk=id)

    component_form = ComponentForm(request.POST or None, instance=component)

    list_of_breadcrumbs = create_list_of_breadcrumbs(list_of_ids_of_components_and_configurations)

    experiment = component.experiment

    component_type = component.component_type
    template_name = "experiment/" + component_type + "_component.html"

    # This is needed for the form to be able to validate the presence of a duration in a pause component only.
    component_form.component_type = component_type

    if component_configuration is None:
        show_remove = True
    else:
        show_remove = False

    back_cancel_url = create_back_cancel_url(component_type, component_configuration, path_of_the_components,
                                             list_of_ids_of_components_and_configurations, experiment, updating)

    return component, component_configuration, component_form, configuration_form, experiment, component_type,\
        template_name, list_of_ids_of_components_and_configurations, show_remove, list_of_breadcrumbs, group,\
        back_cancel_url


def remove_component_and_related_configurations(component,
                                                list_of_ids_of_components_and_configurations,
                                                path_of_the_components):
    # Before removing anything, we need to know where we should redirect to.

    # If the list has more than one element, it has to have more than two, because the last but one element is a
    # component configuration, which has also to be removed from the path.
    if len(list_of_ids_of_components_and_configurations) > 1:
        path_without_last = path_of_the_components[:path_of_the_components.rfind("-")]
        path_without_last_two = path_without_last[:path_without_last.rfind("-")]
        # The parent of the component configuration has to be a block. Then, redirect_url has no "edit" part.
        redirect_url = "/experiment/component/" + path_without_last_two
    else:
        # Return to the list of components
        redirect_url = "/experiment/" + str(component.experiment.id) + "/components"

    component.delete()

    return redirect_url


@login_required
@permission_required('experiment.change_experiment')
def component_view(request, path_of_the_components):
    component, component_configuration, component_form, configuration_form, experiment, component_type, template_name,\
        list_of_ids_of_components_and_configurations, show_remove, list_of_breadcrumbs, group, back_cancel_url =\
        access_objects_for_view_and_update(request, path_of_the_components)

    # It will always be a block because we don't have a view screen for other components.
    block = get_object_or_404(Block, pk=component.id)
    block_form = BlockForm(request.POST or None, instance=block)
    configuration_list, configuration_list_of_random_components = create_configuration_lists(block)

    duration_value = calculate_block_duration(block)
    # Criate a string converting to appropriate units
    duration_string = convert_to_string(duration_value)

    # It is not possible to edit fields while viewing a block.
    for form in {block_form, component_form}:
        for field in form.fields:
            form.fields[field].widget.attrs['disabled'] = True

    if request.method == "POST":
        if request.POST['action'] == "save":
            if configuration_form is not None:
                if configuration_form.is_valid():
                    configuration_form.save()
                    messages.success(request, 'Uso do passo atualizado com sucesso.')
                    return HttpResponseRedirect(back_cancel_url)
        elif request.POST['action'] == "remove":
            redirect_url = remove_component_and_related_configurations(component,
                                                                       list_of_ids_of_components_and_configurations,
                                                                       path_of_the_components)
            return HttpResponseRedirect(redirect_url)
        elif request.POST['action'][:7] == "remove-":
            # If action starts with 'remove-' it means that a child is being removed.
            component_configuration_id_to_be_deleted = request.POST['action'].split("-")[-1]
            component_configuration = get_object_or_404(ComponentConfiguration,
                                                        pk=int(component_configuration_id_to_be_deleted))

            order_of_removed = component_configuration.order
            parent_of_removed = component_configuration.parent_id
            component_configuration.delete()
            last_component_configuration = ComponentConfiguration.objects.filter(
                parent_id=parent_of_removed, random_position=True).order_by('order').last()

            # If the order of the removed component is smaller than the order of the last random-positioned element,
            # assign the order of the removed to the last random-positioned element. This way, for the user, it is like
            # removing the last position for random components.
            if last_component_configuration is not None and last_component_configuration.order > order_of_removed:
                last_component_configuration.order = order_of_removed
                last_component_configuration.save()

            redirect_url = reverse("component_view", args=(path_of_the_components,))
            return HttpResponseRedirect(redirect_url)

    component_type_choices = []
    for type, type_name in Component.COMPONENT_TYPES:
        component_type_choices.append((type, type_name, icon_class.get(type)))

    context = {
        "back_cancel_url": back_cancel_url,
        "block_duration": duration_string,
        "component": block,
        "component_configuration": component_configuration,
        "component_form": component_form,
        "configuration_form": configuration_form,
        "configuration_list": configuration_list,
        "configuration_list_of_random_components": configuration_list_of_random_components,
        "experiment": experiment,
        "group": group,
        "icon_class": icon_class,
        "list_of_breadcrumbs": list_of_breadcrumbs,
        "path_of_the_components": path_of_the_components,
        "show_remove": show_remove,
        "specific_form": block_form,
        "type_of_the_parent_block": block.type,
        "component_type_choices": component_type_choices,
    }

    return render(request, template_name, context)


def sort_without_using_order(configuration_list_of_random_components):
    for configuration in configuration_list_of_random_components:
        configuration.component.icon_class = icon_class[configuration.component.component_type]

    # Create a temporary list of tuples from the query_set to be able to sort by get_component_type_display,
    # identification and name.
    temp_list_of_tuples = []

    for cc in configuration_list_of_random_components:
        temp_list_of_tuples.append((cc,
                                    cc.component.get_component_type_display(),
                                    cc.component.identification,
                                    cc.name))

    temp_list_of_tuples.sort(key=itemgetter(1, 2, 3))

    # Reduce the complexity by creating list of component configurations without having tuples.
    configuration_list_of_random_components = []

    for tuple in temp_list_of_tuples:
        configuration_list_of_random_components.append(tuple[0])

    return configuration_list_of_random_components


def create_configuration_lists(block):
    configuration_list = ComponentConfiguration.objects.filter(parent=block)

    if block.type == "sequence":
        configuration_list = configuration_list.order_by('order')

        # As it is not possible to sort_by get_component_type_display, filter without sorting and sort later.
        configuration_list_of_random_components = sort_without_using_order(
            configuration_list.filter(random_position=True))
    else:
        configuration_list = sort_without_using_order(configuration_list)
        configuration_list_of_random_components = None

    for configuration in configuration_list:
        configuration.component.icon_class = icon_class[configuration.component.component_type]

    return configuration_list, configuration_list_of_random_components


@login_required
@permission_required('experiment.change_experiment')
def component_update(request, path_of_the_components):
    component, component_configuration, component_form, configuration_form, experiment, component_type, template_name,\
        list_of_ids_of_components_and_configurations, show_remove, list_of_breadcrumbs, group, back_cancel_url =\
        access_objects_for_view_and_update(request, path_of_the_components, updating=True)

    questionnaire_id = None
    questionnaire_title = None
    configuration_list = []
    configuration_list_of_random_components = []
    specific_form = None
    duration_string = None

    if component_type == 'instruction':
        instruction = get_object_or_404(Instruction, pk=component.id)
        specific_form = InstructionForm(request.POST or None, instance=instruction)
    elif component_type == 'stimulus':
        stimulus = get_object_or_404(Stimulus, pk=component.id)
        specific_form = StimulusForm(request.POST or None, instance=stimulus)
    elif component_type == 'questionnaire':
        questionnaire = get_object_or_404(Questionnaire, pk=component.id)
        questionnaire_details = Questionnaires().find_questionnaire_by_id(questionnaire.lime_survey_id)

        if questionnaire_details:
            questionnaire_id = questionnaire_details['sid'],
            questionnaire_title = questionnaire_details['surveyls_title']
    elif component_type == 'block':
        block = get_object_or_404(Block, pk=component.id)
        specific_form = BlockForm(request.POST or None, instance=block)
        configuration_list, configuration_list_of_random_components = create_configuration_lists(block)
        duration_value = calculate_block_duration(block)
        # Criate a string converting to appropriate units
        duration_string = convert_to_string(duration_value)

    if request.method == "POST":
        if request.POST['action'] == "save":
            if configuration_form is None:
                # There is no specific form for a these component types.
                if component.component_type == "questionnaire" or component.component_type == "task" or \
                        component.component_type == "task_experiment" or component.component_type == 'pause':
                    if component_form.is_valid():
                        # Only save if there was a change.
                        if component_form.has_changed():
                            component_form.save()
                            messages.success(request, 'Passo alterado com sucesso.')
                        else:
                            messages.success(request, 'Não há alterações para salvar.')

                        return HttpResponseRedirect(back_cancel_url)

                elif specific_form.is_valid() and component_form.is_valid():
                    # Only save if there was a change.
                    if component_form.has_changed() or specific_form.has_changed():
                        if component.component_type == 'block':
                            block = specific_form.save(commit=False)

                            # When changing from 'some mandatory' to 'all mandatory', we must set number to null, so
                            # that we know that all components are mandatory.
                            if "number_of_mandatory_components" not in request.POST:
                                block.number_of_mandatory_components = None

                            block.save()
                        else:
                            specific_form.save()

                        component_form.save()
                        messages.success(request, 'Passo alterado com sucesso.')
                    else:
                        messages.success(request, 'Não há alterações para salvar.')

                    return HttpResponseRedirect(back_cancel_url)

            elif configuration_form.is_valid():
                # Only save if there was a change.
                if configuration_form.has_changed():
                    configuration_form.save()
                    messages.success(request, 'Uso do passo atualizado com sucesso.')
                else:
                    messages.success(request, 'Não há alterações para salvar.')

                return HttpResponseRedirect(back_cancel_url)
        elif request.POST['action'] == "remove":
            redirect_url = remove_component_and_related_configurations(component,
                                                                       list_of_ids_of_components_and_configurations,
                                                                       path_of_the_components)
            return HttpResponseRedirect(redirect_url)

    type_of_the_parent_block = None

    # It is not possible to edit the component fields while editing a component configuration.
    if component_configuration is not None:
        if component_type != "questionnaire" and component_type != 'task' and component_type != 'task_experiment':
            for field in specific_form.fields:
                specific_form.fields[field].widget.attrs['disabled'] = True

        for field in component_form.fields:
            component_form.fields[field].widget.attrs['disabled'] = True

        type_of_the_parent_block = Block.objects.get(id=component_configuration.parent_id).type


    context = {
        "back_cancel_url": back_cancel_url,
        "block_duration": duration_string,
        "component_configuration": component_configuration,
        "component_form": component_form,
        "configuration_form": configuration_form,
        "configuration_list": configuration_list,
        "configuration_list_of_random_components": configuration_list_of_random_components,
        "icon_class": icon_class,
        "experiment": experiment,
        "group": group,
        "list_of_breadcrumbs": list_of_breadcrumbs,
        "path_of_the_components": path_of_the_components,
        "questionnaire_id": questionnaire_id,
        "questionnaire_title": questionnaire_title,
        "show_remove": show_remove,
        "specific_form": specific_form,
        "updating": True,
        "type_of_the_parent_block": type_of_the_parent_block,
    }

    return render(request, template_name, context)


def access_objects_for_add_new_and_reuse(component_type, path_of_the_components):
    template_name = "experiment/" + component_type + "_component.html"
    list_of_ids_of_components_and_configurations = path_of_the_components.split(delimiter)
    list_of_breadcrumbs = create_list_of_breadcrumbs(list_of_ids_of_components_and_configurations)

    block = None
    group = None

    if len(list_of_ids_of_components_and_configurations) > 1 or path_of_the_components[0] != "G":
        # The last id of the list is the block where the new component will be added.
        block_id = list_of_ids_of_components_and_configurations[-1]
        block = get_object_or_404(Block, pk=block_id)
        experiment = block.experiment
    if path_of_the_components[0] == "G":
        # The id of the group comes after "G"
        group_id = int(list_of_ids_of_components_and_configurations[0][1:])
        group = get_object_or_404(Group, pk=group_id)
        experiment = group.experiment

    existing_component_list = Component.objects.filter(experiment=experiment, component_type=component_type)
    specific_form = None

    # If configuring a new experimental protocol for a group, return to the group. Otherwise, return to the parent
    # block.
    if len(list_of_ids_of_components_and_configurations) == 1 and path_of_the_components[0] == 'G':
        back_cancel_url = "/experiment/group/" + str(group.id)
    else:
        back_cancel_url = "/experiment/component/" + path_of_the_components

    return existing_component_list, experiment, group, list_of_breadcrumbs, block, template_name, specific_form, \
           list_of_ids_of_components_and_configurations, back_cancel_url


@login_required
@permission_required('experiment.change_experiment')
def component_add_new(request, path_of_the_components, component_type):
    existing_component_list, experiment, group, list_of_breadcrumbs, block, template_name,\
        specific_form, list_of_ids_of_components_and_configurations, back_cancel_url = \
        access_objects_for_add_new_and_reuse(component_type, path_of_the_components)

    component_form = ComponentForm(request.POST or None)
    # This is needed for the form to be able to validate the presence of a duration in a pause component only.
    component_form.component_type = component_type

    questionnaires_list = []
    specific_form = None
    duration_string = None

    if component_type == 'instruction':
        specific_form = InstructionForm(request.POST or None)
    elif component_type == 'stimulus':
        specific_form = StimulusForm(request.POST or None)
    elif component_type == 'questionnaire':
        questionnaires_list = Questionnaires().find_all_active_questionnaires()
    elif component_type == 'block':
        specific_form = BlockForm(request.POST or None, initial={'number_of_mandatory_components': None})
        duration_string = "0"

    if request.method == "POST":
        new_specific_component = None

        if component_type == 'questionnaire':
            new_specific_component = Questionnaire()
            new_specific_component.lime_survey_id = request.POST['questionnaire_selected']
        elif component_type == 'pause':
            new_specific_component = Pause()
        elif component_type == 'task':
            new_specific_component = Task()
        elif component_type == 'task_experiment':
            new_specific_component = TaskForTheExperimenter()
        elif specific_form.is_valid():
            new_specific_component = specific_form.save(commit=False)

        if component_form.is_valid():
            component = component_form.save(commit=False)
            new_specific_component.description = component.description
            new_specific_component.identification = component.identification
            new_specific_component.component_type = component_type
            new_specific_component.experiment = experiment
            new_specific_component.save()

            # Check if we are configuring a new experimental protocol, which does not have a component configuration.
            if group is None or len(list_of_ids_of_components_and_configurations) > 1:
                new_configuration = ComponentConfiguration()
                new_configuration.component = new_specific_component
                new_configuration.parent = block

                if block.type == 'sequence':
                    new_configuration.random_position = False

                new_configuration.save()

                messages.success(request, 'Passo incluído com sucesso.')

                redirect_url = reverse("component_edit",
                                       args=(path_of_the_components + "-U" + str(new_configuration.id), ))
            else:
                group.experimental_protocol = new_specific_component
                group.save()

                messages.success(request, 'Protocolo experimental incluído com sucesso.')

                redirect_url = reverse("component_view",
                                       args=(path_of_the_components + "-" + str(new_specific_component.id), ))

            return HttpResponseRedirect(redirect_url)

    context = {
        "back_cancel_url": back_cancel_url,
        "block": block,
        "block_duration": duration_string,
        "can_reuse": True,
        "component_form": component_form,
        "creating": True,
        "existing_component_list": existing_component_list,
        "experiment": experiment,
        "group": group,
        "list_of_breadcrumbs": list_of_breadcrumbs,
        "questionnaires_list": questionnaires_list,
        "path_of_the_components": path_of_the_components,
        "specific_form": specific_form,
    }

    return render(request, template_name, context)


@login_required
@permission_required('experiment.change_experiment')
def component_reuse(request, path_of_the_components, component_id):
    component_to_add = get_object_or_404(Component, pk=component_id)
    component_type = component_to_add.component_type

    existing_component_list, experiment, group, list_of_breadcrumbs, block, template_name,\
        specific_form, list_of_ids_of_components_and_configurations, back_cancel_url = \
        access_objects_for_add_new_and_reuse(component_type, path_of_the_components)

    component_form = ComponentForm(request.POST or None, instance=component_to_add)
    # This is needed for the form to be able to validate the presence of a duration in a pause component only.
    component_form.component_type = component_type

    questionnaire_id = None
    questionnaire_title = None
    specific_form = None
    duration_string = None

    if component_type == 'instruction':
        instruction = get_object_or_404(Instruction, pk=component_to_add.id)
        specific_form = InstructionForm(request.POST or None, instance=instruction)
    elif component_type == 'stimulus':
        stimulus = get_object_or_404(Stimulus, pk=component_to_add.id)
        specific_form = StimulusForm(request.POST or None, instance=stimulus)
    elif component_type == 'questionnaire':
        questionnaire = get_object_or_404(Questionnaire, pk=component_to_add.id)
        questionnaire_details = Questionnaires().find_questionnaire_by_id(questionnaire.lime_survey_id)

        if questionnaire_details:
            questionnaire_id = questionnaire_details['sid'],
            questionnaire_title = questionnaire_details['surveyls_title']
    elif component_type == 'block':
        sub_block = get_object_or_404(Block, pk=component_id)
        specific_form = BlockForm(request.POST or None, instance=sub_block)
        duration_value = calculate_block_duration(sub_block)
        # Create a string converting to appropriate units
        duration_string = convert_to_string(duration_value)

    if component_type == 'questionnaire':
        for field in component_form.fields:
            component_form.fields[field].widget.attrs['disabled'] = True
    else:
        for field in component_form.fields:
            component_form.fields[field].widget.attrs['disabled'] = True

        if component_type != 'pause' and component_type != 'task' and component_type != 'task_experiment':
            for field in specific_form.fields:
                specific_form.fields[field].widget.attrs['disabled'] = True

    if request.method == "POST":
        if len(list_of_ids_of_components_and_configurations) == 1 and path_of_the_components[0] == "G":
            # If this is a reuse for creating the root of a group's experimental protocol, no component_configuration
            # has to be created.
            group = Group.objects.get(id=path_of_the_components[1:])
            group.experimental_protocol = component_to_add
            group.save()

            redirect_url = reverse("component_view",
                                   args=(path_of_the_components + "-" + str(component_to_add.id), ))
        else:
            new_configuration = ComponentConfiguration()
            new_configuration.component = component_to_add
            new_configuration.parent = block

            if block.type == 'sequence':
                new_configuration.random_position = False

            new_configuration.save()

            redirect_url = reverse("component_edit",
                                   args=(path_of_the_components + "-U" + str(new_configuration.id), ))

        messages.success(request, 'Passo incluído com sucesso.')
        return HttpResponseRedirect(redirect_url)

    context = {
        "back_cancel_url": back_cancel_url,
        "block": block,
        "block_duration": duration_string,
        "component_form": component_form,
        "creating": True, # So that the "Use" button is shown.
        "existing_component_list": existing_component_list,
        "experiment": experiment,
        "group": group,
        "list_of_breadcrumbs": list_of_breadcrumbs,
        "path_of_the_components": path_of_the_components,
        "questionnaire_id": questionnaire_id,
        "questionnaire_title": questionnaire_title,
        "reusing": True,
        "specific_form": specific_form,
    }

    return render(request, template_name, context)
