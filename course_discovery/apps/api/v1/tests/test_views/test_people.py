# pylint: disable=redefined-builtin,no-member
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import IntegrityError
from mock import mock
from rest_framework.reverse import reverse
from testfixtures import LogCapture

from course_discovery.apps.api.v1.tests.test_views.mixins import APITestCase, SerializationMixin
from course_discovery.apps.api.v1.views.people import logger as people_logger
from course_discovery.apps.core.tests.factories import USER_PASSWORD, UserFactory
from course_discovery.apps.course_metadata.models import Person
from course_discovery.apps.course_metadata.people import MarketingSitePeople
from course_discovery.apps.course_metadata.tests import toggle_switch
from course_discovery.apps.course_metadata.tests.factories import OrganizationFactory, PersonFactory, PositionFactory

User = get_user_model()


class PersonViewSetTests(SerializationMixin, APITestCase):
    """ Tests for the person resource. """
    people_list_url = reverse('api:v1:person-list')

    def setUp(self):
        super(PersonViewSetTests, self).setUp()
        self.user = UserFactory()
        self.target_permissions = Permission.objects.filter(
            codename__in=['add_person', 'change_person', 'delete_person']
        )
        internal_test_group = Group.objects.create(name='internal-test')
        internal_test_group.permissions.add(*self.target_permissions)
        self.user.groups.add(internal_test_group)
        self.client.login(username=self.user.username, password=USER_PASSWORD)
        self.person = PersonFactory(partner=self.partner)
        self.organization = OrganizationFactory(partner=self.partner)
        PositionFactory(person=self.person, organization=self.organization)
        toggle_switch('publish_person_to_marketing_site', True)
        self.expected_node = {
            'resource': 'node', ''
            'id': '28691',
            'uuid': '18d5542f-fa80-418e-b416-455cfdeb4d4e',
            'uri': 'https://stage.edx.org/node/28691'
        }

    def test_create_with_authentication(self):
        """ Verify endpoint successfully creates a person. """
        with mock.patch.object(MarketingSitePeople, 'publish_person', return_value=self.expected_node):
            response = self.client.post(self.people_list_url, self._person_data(), format='json')
            self.assertEqual(response.status_code, 201)

        data = self._person_data()
        person = Person.objects.last()
        self.assertDictEqual(response.data, self.serialize_person(person))
        self.assertEqual(person.given_name, data['given_name'])
        self.assertEqual(person.family_name, data['family_name'])
        self.assertEqual(person.bio, data['bio'])
        self.assertEqual(person.position.title, data['position']['title'])
        self.assertEqual(person.position.organization, self.organization)
        self.assertEqual(sorted([work.value for work in person.person_works.all()]), sorted(data['works']))
        self.assertEqual(
            sorted([social.value for social in person.person_networks.all()]),
            sorted([data['urls']['facebook'], data['urls']['twitter'], data['urls']['blog']])
        )

    def test_create_without_drupal_client_settings(self):
        """ Verify that if credentials are missing api will return the error. """
        self.partner.marketing_site_api_username = None
        self.partner.save()
        data = self._person_data()

        with LogCapture(people_logger.name) as log_capture:
            response = self.client.post(self.people_list_url, self._person_data(), format='json')
            self.assertEqual(response.status_code, 400)
            log_capture.check(
                (
                    people_logger.name,
                    'ERROR',
                    'An error occurred while adding the person [{}]-[{}] to the marketing site.'.format(
                        data['given_name'], data['family_name']
                    )
                )
            )

    def test_create_with_api_exception(self):
        """ Verify that after creating drupal page if serializer fail due to any error, message
        will be logged and drupal page will be deleted. """

        data = self._person_data()
        with mock.patch.object(MarketingSitePeople, 'publish_person', return_value=self.expected_node):
            with mock.patch(
                'course_discovery.apps.api.v1.views.people.PersonViewSet.perform_create',
                side_effect=IntegrityError
            ):
                with mock.patch.object(MarketingSitePeople, 'delete_person', return_value=None):
                    with LogCapture(people_logger.name) as log_capture:
                        response = self.client.post(self.people_list_url, self._person_data(), format='json')
                        self.assertEqual(response.status_code, 400)
                        log_capture.check(
                            (
                                people_logger.name,
                                'ERROR',
                                'An error occurred while adding the person [{}]-[{}]-[{}].'.format(
                                    data['given_name'], data['family_name'], self.expected_node['id']
                                )
                            )
                        )

    def test_create_without_authentication(self):
        """ Verify authentication is required when creating a person. """
        self.client.logout()
        Person.objects.all().delete()

        response = self.client.post(self.people_list_url)
        assert response.status_code == 403
        assert Person.objects.count() == 0

    def test_create_without_permission(self):
        """ Verify group is required when creating a person. """
        self.client.logout()
        new_user = UserFactory()
        new_user.groups.clear()
        self.client.login(username=new_user.username, password=USER_PASSWORD)
        current_people_count = Person.objects.count()
        response = self.client.post(self.people_list_url)
        assert response.status_code == 403
        assert Person.objects.count() == current_people_count

    def test_get(self):
        """ Verify the endpoint returns the details for a single person. """
        url = reverse('api:v1:person-detail', kwargs={'uuid': self.person.uuid})

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, self.serialize_person(self.person))

    def test_get_without_authentication(self):
        """ Verify the endpoint shows auth error when the details for a single person unauthenticated """
        self.client.logout()
        url = reverse('api:v1:person-detail', kwargs={'uuid': self.person.uuid})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_list(self):
        """ Verify the endpoint returns a list of all people. """
        response = self.client.get(self.people_list_url)
        self.assertEqual(response.status_code, 200)
        self.assertListEqual(response.data['results'], self.serialize_person(Person.objects.all(), many=True))

    def test_list_filter_by_slug(self):
        """ Verify the endpoint allows people to be filtered by slug. """
        person = PersonFactory()
        url = '{root}?slug={slug}'.format(root=self.people_list_url, slug=person.slug)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertListEqual(response.data['results'], self.serialize_person([person], many=True))

    def test_create_without_waffle_switch(self):
        """ Verify endpoint shows error message if waffle switch is disabled. """
        toggle_switch('publish_person_to_marketing_site', False)
        response = self.client.post(self.people_list_url, self._person_data(), format='json')
        self.assertEqual(response.status_code, 400)

    def _person_data(self):
        return {
            'given_name': "Robert",
            'family_name': "Ford",
            'email': "test@example.com",
            'bio': "The maze is not for him.",
            'position': {
                'title': "Park Director",
                'organization': self.organization.id
            },
            'works': ["Delores", "Teddy", "Maive"],
            'urls': {
                'facebook': 'http://www.facebook.com/hopkins',
                'twitter': 'http://www.twitter.com/hopkins',
                'blog': 'http://www.blog.com/hopkins'
            }
        }

    def test_update(self):
        """Verify that people data can be updated using endpoint."""
        url = reverse('api:v1:person-detail', kwargs={'uuid': self.person.uuid})

        data = {
            'given_name': "updated",
            'family_name': "name",
            'bio': "updated bio",
            'position': {
                'title': "new title",
                'organization': self.organization.id
            },
            'works': ["new", "added"],
            'urls': {
                'facebook': 'http://www.facebook.com/new',
                'twitter': 'http://www.twitter.com/new',
            }
        }

        response = self.client.patch(url, data, format='json')
        self.assertEqual(response.status_code, 200)

        updated_person = Person.objects.get(id=self.person.id)

        self.assertEqual(updated_person.given_name, data['given_name'])
        self.assertEqual(updated_person.family_name, data['family_name'])
        self.assertEqual(updated_person.bio, data['bio'])
        self.assertEqual(updated_person.position.title, data['position']['title'])
        self.assertEqual(updated_person.person_works.all()[0].value, data['works'][0])
        self.assertEqual(updated_person.person_works.all()[1].value, data['works'][1])
        self.assertEqual(updated_person.person_networks.get(type='facebook').value, data['urls']['facebook'])
        self.assertEqual(updated_person.person_networks.get(type='twitter').value, data['urls']['twitter'])
        self.assertFalse(updated_person.person_networks.filter(type='blog').exists())
