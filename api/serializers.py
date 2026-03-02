from rest_framework import serializers
from django.contrib.auth.models import User
from .models import Skill, Job, CandidateProfile, Resume, JobApplication, MatchScore, UserProfile, HRProfile

class HRProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = HRProfile
        fields = ('id', 'company_name', 'industry', 'logo')


class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    role = serializers.CharField(write_only=True, required=False)
    user_role = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'password', 'role', 'user_role')

    def get_user_role(self, obj):
        try:
            return obj.user_profile.role
        except:
            return 'job_seeker'

    def create(self, validated_data):
        role = validated_data.pop('role', 'job_seeker')
        user = User.objects.create_user(**validated_data)
        
        # Create UserProfile
        UserProfile.objects.create(user=user, role=role)
        
        # Create specific profile based on role
        if role == 'hr':
            HRProfile.objects.create(user=user)
        else:
            CandidateProfile.objects.create(user=user)
            
        return user

class SkillSerializer(serializers.ModelSerializer):
    class Meta:
        model = Skill
        fields = '__all__'

class JobSerializer(serializers.ModelSerializer):
    required_skills = SkillSerializer(many=True, read_only=True)
    required_skill_names = serializers.ListField(
        child=serializers.CharField(), write_only=True, required=False
    )

    class Meta:
        model = Job
        fields = ('id', 'title', 'company', 'description', 'required_skills', 'required_skill_names', 'created_at')

    def create(self, validated_data):
        skill_names = validated_data.pop('required_skill_names', [])
        job = Job.objects.create(**validated_data)
        
        skill_objs = []
        for name in skill_names:
            skill, _ = Skill.objects.get_or_create(name=name.lower().strip())
            skill_objs.append(skill)
        job.required_skills.set(skill_objs)
        return job

    def update(self, instance, validated_data):
        skill_names = validated_data.pop('required_skill_names', None)
        instance = super().update(instance, validated_data)
        
        if skill_names is not None:
            skill_objs = []
            for name in skill_names:
                skill, _ = Skill.objects.get_or_create(name=name.lower().strip())
                skill_objs.append(skill)
            instance.required_skills.set(skill_objs)
            
        return instance


class CandidateProfileSerializer(serializers.ModelSerializer):
    skills = SkillSerializer(many=True, read_only=True)
    skill_names = serializers.ListField(
        child=serializers.CharField(), write_only=True, required=False
    )
    user = UserSerializer(read_only=True)

    class Meta:
        model = CandidateProfile
        fields = '__all__'

    def update(self, instance, validated_data):
        skill_names = validated_data.pop('skill_names', None)
        instance = super().update(instance, validated_data)
        
        if skill_names is not None:
            skill_objs = []
            for name in skill_names:
                skill, _ = Skill.objects.get_or_create(name=name.lower().strip())
                skill_objs.append(skill)
            instance.skills.set(skill_objs)
            
        return instance


class ResumeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Resume
        fields = '__all__'

class JobApplicationSerializer(serializers.ModelSerializer):
    job_details = JobSerializer(source='job', read_only=True)
    candidate_details = CandidateProfileSerializer(source='candidate', read_only=True)
    candidate_name = serializers.CharField(source='candidate.full_name', read_only=True)
    match_score = serializers.SerializerMethodField()

    class Meta:
        model = JobApplication
        fields = ('id', 'job', 'job_details', 'candidate', 'candidate_details', 'candidate_name', 'resume', 'status', 'applied_at', 'match_score')


    def get_match_score(self, obj):
        try:
            return {
                'score': obj.match_score.score,
                'explanation': obj.match_score.explanation,
                'missing_skills': obj.match_score.missing_skills
            }
        except:
            return None
